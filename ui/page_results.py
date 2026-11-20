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

import pandas as pd
import streamlit as st

from ui_common import job_running, launch_task, project_meta, read_json, read_text, require_project


@st.cache_data(show_spinner=False)
def _render_pdf_page(pdf_path: str, page: int, mtime: float, zoom: float = 1.6) -> bytes:
    import pymupdf  # type: ignore

    doc = pymupdf.open(pdf_path)
    pix = doc[page].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    return pix.tobytes("png")


def _pdf_page_count(pdf_path: str) -> int:
    import pymupdf  # type: ignore

    return len(pymupdf.open(pdf_path))


def _tab_pdf(project: str):
    pdf = os.path.join(project, "final_paper.pdf")
    if not os.path.exists(pdf):
        tex = os.path.join(project, "final", "final_paper.tex")
        if os.path.exists(tex):
            st.info("尚無 PDF（可能未安裝 LaTeX）。以下顯示 LaTeX 原始碼。 No PDF yet (LaTeX missing?). Showing LaTeX source.")
            st.code(read_text(tex), language="latex")
        else:
            st.info("尚無結果。 No results yet.")
        return
    n = _pdf_page_count(pdf)
    c1, c2 = st.columns([3, 1])
    with c2:
        page = st.number_input("頁 Page", 1, n, 1) - 1
        two_up = st.checkbox("雙頁 Two pages", value=True)
        with open(pdf, "rb") as f:
            st.download_button("⬇️ PDF", f.read(), file_name="final_paper.pdf", width="stretch")
    with c1:
        mtime = os.path.getmtime(pdf)
        if two_up and page + 1 < n:
            a, b = st.columns(2)
            a.image(_render_pdf_page(pdf, page, mtime))
            b.image(_render_pdf_page(pdf, page + 1, mtime))
        else:
            st.image(_render_pdf_page(pdf, page, mtime))


def _tab_outline(project: str):
    plan = read_json(os.path.join(project, "outline_plan.json"))
    final = read_json(os.path.join(project, "outline.json"))
    if not plan and not final:
        st.info("尚無大綱。 No outline yet.")
        return
    which = st.radio("版本 Version", ["plan (outline agent)", "with citations (after literature)"], horizontal=True)
    data = plan if which.startswith("plan") else final
    if not data:
        st.info("此版本尚未產生。 Not generated yet.")
        return
    for sec in data.get("section_plan", []):
        with st.expander(f"§ {sec.get('section_title', '?')}"):
            for sub in sec.get("subsections", []):
                st.markdown(f"**{sub.get('subsection_title', '')}**")
                for b in sub.get("content_bullets", []):
                    st.markdown(f"- {b}")
                if sub.get("citation_candidates"):
                    st.caption("cites: " + ", ".join(sub["citation_candidates"]))
    if data.get("plotting_plan"):
        st.markdown("**作圖計畫 Plotting plan**")
        st.dataframe(pd.DataFrame(data["plotting_plan"]), width="stretch")
    with st.expander("原始 JSON Raw JSON"):
        st.json(data)


def _tab_references(project: str):
    cmap = read_json(os.path.join(project, "literature_agent_output", "citation_map.json"))
    if not cmap:
        st.info("尚無文獻。 No references yet.")
        return
    rows = [
        {
            "key": k,
            "title": v.get("title"),
            "year": v.get("year"),
            "venue": v.get("venue"),
            "citations": v.get("citation_count", v.get("citationCount")),
            "section": v.get("found_in_section"),
        }
        for k, v in cmap.items()
    ]
    st.caption(f"{len(rows)} 篇 references")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    bib = os.path.join(project, "literature_agent_output", "references.bib")
    if os.path.exists(bib):
        with st.expander("references.bib"):
            st.code(read_text(bib), language="bibtex")


def _tab_figures(project: str):
    results = read_json(os.path.join(project, "plotting_results.json"), []) or []
    info = read_json(os.path.join(project, "latex_writeup", "figures", "info.json"), []) or []
    if not results and not info:
        st.info("尚無圖表。 No figures yet.")
        return
    for res in results:
        with st.container(border=True):
            c1, c2 = st.columns([3, 2])
            img = os.path.join(project, res.get("image_path", "")) if res.get("image_path") else None
            with c1:
                if img and os.path.exists(img):
                    st.image(img)
                else:
                    st.warning("無圖片 No image" + (f": {res.get('render_error')}" if res.get("render_error") else ""))
                anim = os.path.join(project, res["animation_path"]) if res.get("animation_path") else None
                if anim and os.path.exists(anim):
                    st.video(anim)
            with c2:
                st.markdown(f"**{res.get('figure_id')}** — {res.get('title', '')}")
                st.caption(f"type: {res.get('task_name')} · engine: {res.get('engine', 'image')} · aspect {res.get('aspect_ratio')}"
                           + (" · ⛔ excluded" if res.get("excluded") else ""))
                st.write(res.get("caption", ""))
                with st.expander("描述與審查紀錄 Description & critic history"):
                    st.write(res.get("description", ""))
                    for h in res.get("critic_history", []):
                        st.markdown(f"*Round {h.get('round', 0) + 1}:* {h.get('suggestions', '')}")
                if res.get("code_path") and os.path.exists(os.path.join(project, res["code_path"])):
                    with st.expander("原始碼 Source code"):
                        st.code(read_text(os.path.join(project, res["code_path"])))
    provided = [i for i in info if i.get("source") == "provided"]
    if provided:
        st.markdown("**自備圖片 Provided figures**")
        for item in provided:
            path = os.path.join(project, "latex_writeup", "figures", item["name"])
            if os.path.exists(path) and not path.lower().endswith(".pdf"):
                st.image(path, caption=item.get("caption", ""), width=480)


def _tab_refinement(project: str):
    work = os.path.join(project, "content_refinement_workdir")
    worklog = read_json(os.path.join(work, "content_refinement_worklog.json"), {}) or {}
    reviews_dir = os.path.join(work, "peer_reviews")
    if not worklog and not os.path.isdir(reviews_dir):
        st.info("尚無審稿紀錄。 No refinement data yet.")
        return
    rows = []
    v0 = read_json(os.path.join(reviews_dir, "review_v0.json"), {}) or {}
    if v0:
        rows.append({"version": "v0", "Overall": v0.get("Overall"), "outcome": "baseline"})
    for ver, entry in worklog.items():
        rows.append({"version": ver, "Overall": (entry.get("scores_after") or {}).get("Overall"), "outcome": entry.get("outcome")})
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, width="stretch")
        chart = df.dropna(subset=["Overall"]).set_index("version")["Overall"]
        if len(chart) > 1:
            st.line_chart(chart)
    for ver, entry in worklog.items():
        with st.expander(f"{ver}: {entry.get('outcome')}"):
            st.json(entry)
    if os.path.isdir(reviews_dir):
        for name in sorted(os.listdir(reviews_dir)):
            with st.expander(f"📝 {name}"):
                st.json(read_json(os.path.join(reviews_dir, name), {}))


def _tab_review(project: str):
    st.caption("以審稿人角色對最終論文打分（AgentReview 量表）。 Score the final paper with the AgentReview rubric.")
    running = job_running(project)
    if st.button("🧑‍⚖️ 執行 AI 審稿 Run AI review", disabled=bool(running)):
        launch_task(project, ["review"], "review")
        st.toast("已開始，請到「執行」頁查看進度。 Started; see the Run page.")
    review = read_json(os.path.join(project, "ai_review.json"))
    if review:
        if isinstance(review, dict):
            score_keys = [k for k in ("Overall", "Soundness", "Presentation", "Contribution", "Originality",
                                      "Quality", "Clarity", "Significance", "Confidence") if k in review]
            cols = st.columns(max(1, len(score_keys)))
            for col, k in zip(cols, score_keys):
                col.metric(k, review[k])
            for k in ("Summary", "Strengths", "Weaknesses", "Questions", "Limitations"):
                if review.get(k):
                    st.markdown(f"**{k}**")
                    st.write(review[k])
        with st.expander("JSON"):
            st.json(review)


def _tab_timing(project: str):
    tb = read_json(os.path.join(project, "time_breakdown.json"))
    if not tb:
        st.info("尚無資料。 No data.")
        return
    rows = [{"step": k, "minutes": round(v / 60, 2)} for k, v in tb.items() if k != "Start_Time_Absolute"]
    st.dataframe(pd.DataFrame(rows), hide_index=True)


def render():
    project = require_project()
    if not project:
        return
    meta = project_meta(project)
    st.header(f"🔍 檢查結果 Results — {meta.get('name')}")
    tabs = st.tabs(["📄 論文 Paper", "🧭 大綱 Outline", "📚 文獻 References", "🖼️ 圖表 Figures",
                    "📈 審稿修訂 Refinement", "🧑‍⚖️ AI 審稿 Review", "⏱️ 耗時 Timing"])
    with tabs[0]:
        _tab_pdf(project)
    with tabs[1]:
        _tab_outline(project)
    with tabs[2]:
        _tab_references(project)
    with tabs[3]:
        _tab_figures(project)
    with tabs[4]:
        _tab_refinement(project)
    with tabs[5]:
        _tab_review(project)
    with tabs[6]:
        _tab_timing(project)
