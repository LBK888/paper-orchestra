# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import tempfile

import streamlit as st

from methods.agents.manual_revision_agent import (
    final_paths,
    list_revisions,
    list_sections,
    revert_to,
    unified_diff,
)
from ui_common import (
    image_backend_picker,
    job_running,
    launch_task,
    model_picker,
    project_meta,
    read_json,
    read_text,
    require_project,
    write_json,
    write_text,
)
from utils.code_renderers import DIAGRAM_ENGINES, PLOT_ENGINES


def _instruction_file(project: str, text: str) -> str:
    path = os.path.join(project, "logs", "_last_instruction.txt")
    write_text(path, text)
    return path


def _tab_ai_revision(project: str, meta: dict, running):
    paths = final_paths(project)
    tex = read_text(paths["tex"])
    if not tex:
        st.info("尚無最終 LaTeX。請先執行管線（至少到 sections）。 Run the pipeline first (at least up to sections).")
        return
    sections = ["(whole paper)"] + [s.title for s in list_sections(tex)]
    c1, c2 = st.columns([1, 2])
    with c1:
        target = st.selectbox("修改範圍 Scope", sections, help="只改一節可降低成本與風險。 Revising one section is cheaper and safer.")
    with c2:
        model = model_picker("修訂模型 Revision model", (meta.get("models") or {}).get("revision"), key="rev_model")
    instruction = st.text_area(
        "修改指示 Instruction",
        height=150,
        placeholder="例：把貢獻改寫成三點條列並更強調效率；Related Work 補充與 diffusion 方法的比較；縮短摘要至 150 字。",
    )
    compile_pdf = st.checkbox("修改後重新編譯 PDF Recompile PDF afterwards", value=True)
    if st.button("✍️ 套用修改 Apply", type="primary", disabled=bool(running) or not instruction.strip()):
        args = ["revise", "--instruction_file", _instruction_file(project, instruction), "--model", model]
        if target != "(whole paper)":
            args += ["--section", target]
        if not compile_pdf:
            args.append("--no_compile")
        launch_task(project, args, "revise")
        st.toast("已開始修訂，請到「執行」頁查看進度。 Revision started; see the Run page.")

    st.divider()
    st.subheader("📜 修訂紀錄 Revision history")
    revs = list_revisions(project)
    if not revs:
        st.caption("尚無修訂。 No revisions yet.")
    for rev in reversed(revs):
        with st.expander(f"{rev['id']} · {rev.get('section')} · {rev.get('instruction', '')[:80]}"):
            st.markdown(f"**指示 Instruction:** {rev.get('instruction')}")
            st.markdown(f"**摘要 Summary:** {rev.get('summary', '')}")
            diff = unified_diff(read_text(os.path.join(rev["dir"], "before.tex")), read_text(os.path.join(rev["dir"], "after.tex")))
            st.code(diff[:60000] or "(no changes)", language="diff")
            if st.button("↩️ 還原到此修訂之前 Revert to before this revision", key=f"revert_{rev['id']}", disabled=bool(running)):
                revert_to(project, rev["id"], "before")
                st.success("已還原。記得重新編譯。 Reverted; recompile to update the PDF.")


def _tab_latex(project: str, running):
    paths = final_paths(project)
    tex = read_text(paths["tex"])
    if not tex:
        st.info("尚無最終 LaTeX。 No final LaTeX yet.")
        return
    st.caption(f"`{paths['tex']}`")
    edited = st.text_area("LaTeX", value=tex, height=600, key=f"latex_edit_{os.path.getmtime(paths['tex'])}")
    c1, c2 = st.columns(2)
    if c1.button("💾 儲存 Save", type="primary"):
        from methods.agents.manual_revision_agent import record_revision

        record_revision(project, tex, edited, "Manual LaTeX edit", {"section": "(whole paper)", "summary": "manual edit"})
        write_text(paths["tex"], edited)
        st.success("已儲存（已記錄於修訂紀錄）。 Saved (recorded in history).")
    if c2.button("🛠️ 編譯 PDF Compile", disabled=bool(running)):
        launch_task(project, ["compile"], "compile")
        st.toast("編譯中… Compiling…")


def _tab_outline(project: str, running):
    plan_path = os.path.join(project, "outline_plan.json")
    if not os.path.exists(plan_path) and os.path.exists(os.path.join(project, "outline.json")):
        plan_path = os.path.join(project, "outline.json")
    data = read_json(plan_path)
    if data is None:
        st.info("尚無大綱。先執行 outline 階段。 Run the outline stage first.")
        return
    st.caption("修改大綱後，從 literature 階段重新執行即可套用。 After editing, re-run from the literature stage.")
    text = st.text_area("outline_plan.json", value=json.dumps(data, indent=2, ensure_ascii=False), height=520)
    c1, c2 = st.columns(2)
    if c1.button("💾 儲存大綱 Save outline", type="primary"):
        try:
            write_json(os.path.join(project, "outline_plan.json"), json.loads(text))
            st.success("已儲存。 Saved.")
        except json.JSONDecodeError as exc:
            st.error(f"JSON 格式錯誤 Invalid JSON: {exc}")
    if c2.button("🔁 從 literature 重新執行 Re-run from literature", disabled=bool(running)):
        launch_task(project, ["run", "--start_stage", "literature"], "pipeline_literature-refinement")
        st.toast("已開始。 Started.")


def _tab_figures(project: str, meta: dict, running):
    results_path = os.path.join(project, "plotting_results.json")
    results = read_json(results_path, []) or []
    if not results:
        st.info("沒有自動生成的圖。（自備圖片請到「輸入」頁管理） No generated figures (provided figures live on the Inputs page).")
        return
    st.caption(
        "修改圖說、替換圖片或排除圖後，按下方「同步並從 sections 重新執行」讓論文採用新圖。 "
        "After changing captions / images, use 'Sync & re-run from sections' so the paper picks them up."
    )
    dirty = False
    for i, res in enumerate(results):
        fid = res.get("figure_id")
        slug = (fid or "figure").replace(" ", "_").lower()
        with st.container(border=True):
            c1, c2 = st.columns([2, 3])
            img = os.path.join(project, res["image_path"]) if res.get("image_path") else None
            with c1:
                if img and os.path.exists(img):
                    st.image(img)
                else:
                    st.warning("無圖片 No image")
                up = st.file_uploader("替換圖片 Replace image", type=["png", "jpg", "jpeg"], key=f"rep_{fid}")
                if up is not None and st.button("使用此圖 Use this image", key=f"use_{fid}"):
                    from utils.image_backends import to_png_bytes

                    dst = os.path.join(project, "figures", f"{slug}.png")
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as f:
                        f.write(to_png_bytes(up.getvalue()))
                    results[i]["image_path"] = f"figures/{slug}.png"
                    results[i]["engine"] = "manual"
                    write_json(results_path, results)
                    st.rerun()
            with c2:
                st.markdown(f"**{fid}** — {res.get('title', '')} · `{res.get('engine', 'image')}`")
                cap = st.text_area("圖說 Caption", value=res.get("caption", ""), key=f"fcap_{fid}")
                excl = st.checkbox("不放入論文 Exclude from paper", value=bool(res.get("excluded")), key=f"excl_{fid}")
                if cap != res.get("caption", "") or excl != bool(res.get("excluded")):
                    results[i]["caption"] = cap
                    results[i]["excluded"] = excl
                    dirty = True

                with st.expander("🔁 重新生成 Regenerate with instructions"):
                    instr = st.text_area("指示 Instruction", key=f"rinstr_{fid}",
                                         placeholder="例：改成水平長條圖，加上誤差線；顏色改為藍/橙配色。")
                    engines = PLOT_ENGINES if res.get("task_name") == "plot" else DIAGRAM_ENGINES
                    eng = st.selectbox("引擎 Engine", ["(same)"] + engines, key=f"reng_{fid}")
                    backend = None
                    if eng == "image" or (eng == "(same)" and res.get("engine") == "image"):
                        backend = image_backend_picker("Image backend", meta.get("image_backend"), key=f"rib_{fid}")
                    reuse = st.checkbox("沿用目前描述（較快）Reuse current description (faster)", value=True, key=f"reuse_{fid}")
                    rounds = st.number_input("自我修正輪數 Critic rounds", 0, 6, 1, key=f"rcr_{fid}")
                    if st.button("開始 Regenerate", key=f"regen_{fid}", disabled=bool(running)):
                        args = ["regen-figure", "--figure_id", fid, "--critic_rounds", str(int(rounds))]
                        if instr.strip():
                            args += ["--instruction_file", _instruction_file(project, instr)]
                        if eng != "(same)":
                            args += ["--engine", eng]
                        if backend:
                            args += ["--image_backend", backend]
                        if reuse:
                            args.append("--reuse_description")
                        launch_task(project, args, f"regen_{slug}")
                        st.toast("已開始重新生成。 Regeneration started.")

                code_rel = res.get("code_path")
                code_path = os.path.join(project, code_rel) if code_rel else None
                if code_path and os.path.exists(code_path):
                    with st.expander("🧑‍💻 編輯程式碼並重新繪製 Edit code & re-render"):
                        code = st.text_area("Code", value=read_text(code_path), height=360, key=f"code_{fid}_{os.path.getmtime(code_path)}")
                        if st.button("💾 儲存並繪製 Save & render", key=f"rend_{fid}", disabled=bool(running)):
                            write_text(code_path, code)
                            launch_task(project, ["render-code", "--figure_id", fid], f"render_{slug}")
                            st.toast("繪製中… Rendering…")
    c1, c2 = st.columns(2)
    if dirty and c1.button("💾 儲存圖說/排除設定 Save captions", type="primary"):
        write_json(results_path, results)
        st.success("已儲存。 Saved.")
    if c2.button("🔁 同步並從 sections 重新執行 Sync & re-run from sections", disabled=bool(running)):
        if dirty:
            write_json(results_path, results)
        launch_task(project, ["run", "--start_stage", "sections"], "pipeline_sections-refinement")
        st.toast("已開始。 Started.")


def render():
    project = require_project()
    if not project:
        return
    meta = project_meta(project)
    running = job_running(project)
    st.header(f"✏️ 人工修正 Revise — {meta.get('name')}")
    if running:
        st.warning(f"工作執行中 ({running.get('job')})，部分功能暫停。 A job is running; some actions are disabled.")
    tabs = st.tabs(["🤖 AI 指示修訂 AI revision", "📝 直接編輯 LaTeX", "🧭 大綱 Outline", "🖼️ 圖表 Figures"])
    with tabs[0]:
        _tab_ai_revision(project, meta, running)
    with tabs[1]:
        _tab_latex(project, running)
    with tabs[2]:
        _tab_outline(project, running)
    with tabs[3]:
        _tab_figures(project, meta, running)
