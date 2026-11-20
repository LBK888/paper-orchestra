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

import os

import streamlit as st

from ui_common import (
    image_backend_picker,
    model_picker,
    project_meta,
    read_json,
    read_text,
    require_project,
    update_project,
    write_json,
    write_text,
)
from utils.code_renderers import DIAGRAM_ENGINES, PLOT_ENGINES, engine_available
from utils.project_utils import available_templates

IMG_TYPES = ["png", "jpg", "jpeg", "pdf"]


def _materials_editor(project: str, meta: dict):
    raw = os.path.join(project, "raw_materials")
    key = os.path.basename(project)

    st.subheader("📝 研究想法 Idea")
    idea_path = os.path.join(raw, meta["idea_filename"])
    up = st.file_uploader("上傳 Upload idea (.md/.txt)", type=["md", "txt"], key=f"idea_up_{key}")
    if up is not None:
        write_text(idea_path, up.read().decode("utf-8", errors="replace"))
        st.session_state.pop(f"idea_txt_{key}", None)
        st.success("已上傳。 Uploaded.")
    idea = st.text_area(
        "Idea (Markdown): 問題、方法、貢獻 problem, method, contributions",
        value=read_text(idea_path),
        height=260,
        key=f"idea_txt_{key}",
    )

    st.subheader("🧪 實驗紀錄 Experimental log")
    log_path = os.path.join(raw, meta["experimental_log_filename"])
    up2 = st.file_uploader("上傳 Upload log (.md/.txt)", type=["md", "txt"], key=f"log_up_{key}")
    if up2 is not None:
        write_text(log_path, up2.read().decode("utf-8", errors="replace"))
        st.session_state.pop(f"log_txt_{key}", None)
        st.success("已上傳。 Uploaded.")
    log = st.text_area(
        "Experimental log (Markdown): 設定、數據表、消融 setups, result tables, ablations",
        value=read_text(log_path),
        height=260,
        key=f"log_txt_{key}",
    )
    if st.button("💾 儲存素材 Save materials", type="primary"):
        write_text(idea_path, idea)
        write_text(log_path, log)
        st.success("已儲存。 Saved.")

    st.subheader("🖼️ 自備圖片 Provided figures")
    st.caption(
        "可選：上傳已完成的圖（含說明）。關閉自動作圖時必須提供；開啟時會與生成的圖合併。 "
        "Optional: upload finished figures with captions. Required when figure generation is off; "
        "merged with generated figures when it is on."
    )
    fig_dir = os.path.join(raw, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    info_path = os.path.join(fig_dir, "info.json")
    info = read_json(info_path, []) or []
    ups = st.file_uploader("上傳圖片 Upload figures", type=IMG_TYPES, accept_multiple_files=True, key=f"figs_up_{key}")
    if ups and st.button("加入 Add uploaded figures"):
        names = {i["name"] for i in info}
        for f in ups:
            with open(os.path.join(fig_dir, f.name), "wb") as out:
                out.write(f.getbuffer())
            if f.name not in names:
                info.append({"name": f.name, "caption": ""})
        write_json(info_path, info)
        st.rerun()
    changed = False
    for idx, item in enumerate(list(info)):
        path = os.path.join(fig_dir, item["name"])
        with st.container(border=True):
            c1, c2 = st.columns([1, 2])
            with c1:
                if os.path.exists(path) and not path.lower().endswith(".pdf"):
                    st.image(path, width="stretch")
                else:
                    st.write(f"📄 {item['name']}")
            with c2:
                new_cap = st.text_area("說明 Caption", value=item.get("caption", ""), key=f"cap_{key}_{item['name']}")
                if new_cap != item.get("caption", ""):
                    info[idx]["caption"] = new_cap
                    changed = True
                if st.button("移除 Remove", key=f"rm_{key}_{item['name']}"):
                    info = [i for i in info if i["name"] != item["name"]]
                    if os.path.exists(path):
                        os.remove(path)
                    write_json(info_path, info)
                    st.rerun()
    if changed and st.button("💾 儲存圖說 Save captions"):
        write_json(info_path, info)
        st.success("已儲存。 Saved.")


def _options_editor(project: str, meta: dict):
    key = os.path.basename(project)
    st.subheader("⚙️ 執行選項 Run options")
    templates = available_templates()
    c1, c2, c3 = st.columns(3)
    with c1:
        template = st.selectbox(
            "LaTeX 模板 Template", templates,
            index=templates.index(meta["template"]) if meta.get("template") in templates else 0,
            key=f"tpl_{key}",
        )
    with c2:
        cutoff = st.text_input("文獻截止 Research cutoff (YYYY-MM)", value=meta.get("research_cutoff", ""), key=f"cut_{key}")
    with c3:
        search_backend = st.selectbox(
            "文獻搜尋 Literature search",
            ["auto", "gemini", "semantic_scholar", "llm"],
            index=["auto", "gemini", "semantic_scholar", "llm"].index(meta.get("search_backend", "auto")),
            help="gemini = Google Search grounding；semantic_scholar = S2 搜尋 + LLM 篩選（任何模型）；llm = 模型記憶 + S2 驗證",
            key=f"sb_{key}",
        )

    st.markdown("**LLM 模型 Models** — 格式 `provider:model`，例如 `ollama:qwen3:32b`、`openrouter:anthropic/claude-sonnet-4.5`")
    models = dict(meta.get("models") or {})
    for role, label in (
        ("writer", "撰寫 Writer"),
        ("reflection", "審稿修訂 Reflection"),
        ("plotting", "作圖 Plotting"),
        ("search", "文獻搜尋 Search"),
        ("revision", "人工修正 Revision"),
    ):
        models[role] = model_picker(label, models.get(role), key=f"m_{role}_{key}")

    st.markdown("**圖表 Figures**")
    use_plotting = st.toggle("自動生成圖表 Generate figures with the plotting agent", value=bool(meta.get("use_plotting", True)), key=f"up_{key}")
    c1, c2, c3 = st.columns(3)
    with c1:
        plot_engine = st.selectbox(
            "數據圖引擎 Plot engine", PLOT_ENGINES,
            index=PLOT_ENGINES.index(meta.get("plot_engine", "matplotlib")) if meta.get("plot_engine") in PLOT_ENGINES else 0,
            format_func=lambda e: e + ("" if engine_available(e) else " (未安裝 not installed)"),
            key=f"pe_{key}",
        )
    with c2:
        diagram_engine = st.selectbox(
            "示意圖引擎 Diagram engine", DIAGRAM_ENGINES,
            index=DIAGRAM_ENGINES.index(meta.get("diagram_engine", "image")) if meta.get("diagram_engine") in DIAGRAM_ENGINES else 0,
            format_func=lambda e: {"image": "image (圖片生成模型)"}.get(e, e) + ("" if engine_available(e) else " (未安裝 not installed)"),
            key=f"de_{key}",
        )
    with c3:
        critic = st.number_input("圖表自我修正輪數 Critic rounds", 0, 6, int(meta.get("plotting_max_critic_rounds", 3)), key=f"cr_{key}")
    image_backend = image_backend_picker("示意圖生成 Diagram image", meta.get("image_backend"), key=f"ib_{key}")
    max_ref = st.number_input("內容修訂輪數 Refinement iterations", 0, 6, int(meta.get("max_reflections", 3)), key=f"mr_{key}")
    notes = st.text_area("備註 Notes", value=meta.get("notes", ""), key=f"notes_{key}")

    if st.button("💾 儲存選項 Save options", type="primary", key=f"save_opts_{key}"):
        update_project(
            project,
            template=template,
            research_cutoff=cutoff,
            search_backend=search_backend,
            models=models,
            use_plotting=use_plotting,
            plot_engine=plot_engine,
            diagram_engine=diagram_engine,
            plotting_max_critic_rounds=int(critic),
            image_backend=image_backend,
            max_reflections=int(max_ref),
            notes=notes,
        )
        st.success("已儲存。 Saved. 下一步：到「執行 Run」頁開始。 Next: go to Run.")


def render():
    project = require_project()
    if not project:
        return
    meta = project_meta(project)
    st.header(f"📝 輸入與選項 Inputs — {meta.get('name')}")
    tab1, tab2 = st.tabs(["素材 Materials", "選項 Options"])
    with tab1:
        _materials_editor(project, meta)
    with tab2:
        _options_editor(project, meta)
