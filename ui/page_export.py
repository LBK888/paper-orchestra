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

from ui_common import project_meta, require_project
from utils.export_utils import (
    export_docx,
    export_latex_zip,
    export_markdown,
    export_pdf,
    pandoc_path,
)
from utils.project_utils import export_project_zip

FORMATS = {
    "pdf": ("📄 PDF", export_pdf, "application/pdf"),
    "docx": ("📝 Word (.docx)", export_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "md": ("🗒️ Markdown (.md)", export_markdown, "text/markdown"),
    "latex": ("🧾 LaTeX source (.zip)", export_latex_zip, "application/zip"),
}


def render():
    project = require_project()
    if not project:
        return
    meta = project_meta(project)
    st.header(f"📤 匯出 Export — {meta.get('name')}")
    if not os.path.exists(os.path.join(project, "final", "final_paper.tex")):
        st.info("尚無最終論文。請先執行管線。 No final paper yet; run the pipeline first.")
    st.caption(
        "DOCX/MD 由 pandoc 轉換（含參考文獻與圖片）。 DOCX/MD are converted with pandoc "
        f"({'found: ' + str(pandoc_path()) if pandoc_path() else 'not found → basic built-in converter'})."
    )

    ref_doc = None
    up = st.file_uploader("（選用）Word 樣式範本 Optional reference .docx for styles", type=["docx"])
    if up is not None:
        ref_doc = os.path.join(project, "exports", "reference.docx")
        os.makedirs(os.path.dirname(ref_doc), exist_ok=True)
        with open(ref_doc, "wb") as f:
            f.write(up.getbuffer())

    for fmt, (label, func, mime) in FORMATS.items():
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.markdown(f"**{label}**")
            key = f"export_{fmt}_{os.path.basename(project)}"
            if c2.button("產生 Generate", key=f"gen_{fmt}"):
                with st.spinner("轉換中… Converting…"):
                    try:
                        path = func(project, reference_docx=ref_doc) if fmt == "docx" else func(project)
                        st.session_state[key] = path
                    except Exception as exc:
                        st.session_state.pop(key, None)
                        c1.error(str(exc)[:1500])
            path = st.session_state.get(key)
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    c3.download_button("⬇️ 下載 Download", f.read(), file_name=os.path.basename(path), mime=mime, key=f"dl_{fmt}")
                c1.caption(f"`{path}`")
                if fmt == "md":
                    media = os.path.join(os.path.dirname(path), "paper_media")
                    if os.path.isdir(media):
                        c1.caption(f"圖片在 Images in `{media}`")

    st.divider()
    st.subheader("💼 整個專案 Whole project (.zip)")
    st.caption("可在另一台電腦用「專案 → 匯入」開啟。 Re-open on another machine with Projects → Import.")
    if st.button("打包 Build project zip"):
        st.session_state["project_zip"] = export_project_zip(project)
    zp = st.session_state.get("project_zip")
    if zp and os.path.exists(zp):
        with open(zp, "rb") as f:
            st.download_button("⬇️ 下載專案 Download project", f.read(), file_name=os.path.basename(zp), mime="application/zip")
