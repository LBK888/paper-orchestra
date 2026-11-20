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

"""PaperOrchestra Studio — run with `streamlit run ui/app.py` (or start.bat)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("PYTHONUTF8", "1")

import streamlit as st  # noqa: E402

st.set_page_config(page_title="PaperOrchestra Studio", page_icon="🎻", layout="wide")

import page_export  # noqa: E402
import page_inputs  # noqa: E402
import page_projects  # noqa: E402
import page_results  # noqa: E402
import page_revise  # noqa: E402
import page_run  # noqa: E402
import page_settings  # noqa: E402
from ui_common import current_project, job_running, project_meta  # noqa: E402
from utils.project_utils import project_state  # noqa: E402

PAGES = {
    "projects": ("📁 專案 Projects", page_projects.render),
    "inputs": ("📝 輸入 Inputs", page_inputs.render),
    "run": ("▶️ 執行 Run & status", page_run.render),
    "results": ("🔍 結果 Results", page_results.render),
    "revise": ("✏️ 修正 Revise", page_revise.render),
    "export": ("📤 匯出 Export", page_export.render),
    "settings": ("⚙️ 設定 Settings", page_settings.render),
}

if "nav_request" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("nav_request")
st.session_state.setdefault("nav", "projects")

with st.sidebar:
    st.title("🎻 PaperOrchestra")
    st.caption("Multi-agent AI paper writing studio")
    project = current_project()
    if project:
        meta = project_meta(project)
        running = job_running(project)
        st.markdown(f"**目前專案 Project:** {meta.get('name')}")
        st.caption(f"`{os.path.relpath(project, ROOT)}` · {'🔄 ' + str(running.get('job')) if running else project_state(project)}")
    else:
        st.info("尚未開啟專案 No project open")
    st.radio(
        "頁面 Pages",
        list(PAGES.keys()),
        format_func=lambda k: PAGES[k][0],
        key="nav",
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("CLI: `python paper_writing_cli.py -h` · `python po_tasks.py -h`")

PAGES[st.session_state["nav"]][1]()
