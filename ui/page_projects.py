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
import shutil
import tempfile

import streamlit as st

from ui_common import ROOT, fmt_time, job_running
from utils.project_utils import (
    archive_project,
    create_project,
    export_project_zip,
    import_project_zip,
    list_projects,
    projects_root,
    save_project,
    load_project,
)


def _open(path: str):
    st.session_state["project_path"] = path
    st.session_state["nav_request"] = "inputs"
    st.rerun()


def _load_cvpr_example(path: str):
    ex_dir = os.path.join(ROOT, "frontend", "examples")
    with open(os.path.join(ex_dir, "cvpr_example.json"), "r", encoding="utf-8") as f:
        ex = json.load(f)
    raw = os.path.join(path, "raw_materials")
    os.makedirs(os.path.join(raw, "figures"), exist_ok=True)
    with open(os.path.join(raw, "idea.md"), "w", encoding="utf-8") as f:
        f.write(ex.get("idea", ""))
    with open(os.path.join(raw, "experimental_log.md"), "w", encoding="utf-8") as f:
        f.write(ex.get("log", ""))
    if ex.get("figure_path"):
        src = os.path.join(ex_dir, ex["figure_path"])
        if os.path.exists(src):
            shutil.copy(src, os.path.join(raw, "figures", os.path.basename(src)))
            with open(os.path.join(raw, "figures", "info.json"), "w", encoding="utf-8") as f:
                json.dump([{"name": os.path.basename(src), "caption": ex.get("figure_caption", "")}], f, indent=4)
    meta = load_project(path)
    meta["template"] = "cvpr2025"
    save_project(path, meta)


def render():
    st.header("📁 專案 Projects")
    st.caption(f"專案資料夾 Projects folder: `{projects_root()}`")

    c1, c2 = st.columns(2)
    with c1:
        with st.form("new_project"):
            st.subheader("建立新專案 New project")
            name = st.text_input("專案名稱 Name", placeholder="my_cvpr_paper")
            with_example = st.checkbox("載入 CVPR 範例素材 Load the CVPR example materials")
            if st.form_submit_button("建立 Create", type="primary"):
                if not name.strip():
                    st.error("請輸入名稱。 Enter a name.")
                else:
                    try:
                        path = create_project(name.strip())
                        if with_example:
                            _load_cvpr_example(path)
                        _open(path)
                    except FileExistsError as exc:
                        st.error(str(exc))
    with c2:
        st.subheader("匯入專案 Import (.zip)")
        up = st.file_uploader("PaperOrchestra project zip", type=["zip"], key="import_zip")
        if up is not None and st.button("匯入 Import"):
            tmp = os.path.join(tempfile.mkdtemp(), up.name)
            with open(tmp, "wb") as f:
                f.write(up.getbuffer())
            try:
                _open(import_project_zip(tmp))
            except Exception as exc:
                st.error(f"匯入失敗 Import failed: {exc}")

    st.divider()
    st.subheader("現有專案 Existing projects")
    projects = list_projects()
    if not projects:
        st.info("尚無專案。 No projects yet.")
        return
    current = st.session_state.get("project_path")
    for proj in projects:
        with st.container(border=True):
            cols = st.columns([3, 2, 2, 1, 1, 1])
            marker = "👉 " if current and os.path.abspath(current) == os.path.abspath(proj["path"]) else ""
            cols[0].markdown(f"**{marker}{proj['name']}**  \n`{proj['folder']}`")
            cols[1].markdown(f"狀態 State: `{proj['state']}`" + ("  \n📄 PDF" if proj["has_pdf"] else ""))
            cols[2].caption(f"更新 Updated  \n{fmt_time(proj['updated_at'])}")
            if cols[3].button("開啟 Open", key=f"open_{proj['folder']}"):
                _open(proj["path"])
            zip_key = f"zip_{proj['folder']}"
            if cols[4].button("打包 Zip", key=f"mkzip_{proj['folder']}"):
                st.session_state[zip_key] = export_project_zip(proj["path"])
            if st.session_state.get(zip_key) and os.path.exists(st.session_state[zip_key]):
                with open(st.session_state[zip_key], "rb") as f:
                    cols[4].download_button("⬇️", f.read(), file_name=os.path.basename(st.session_state[zip_key]), key=f"dl_{proj['folder']}")
            with cols[5].popover("封存 Archive"):
                st.write("移到 `projects/.trash`（可復原）。 Moves the project to projects/.trash (recoverable).")
                if job_running(proj["path"]):
                    st.warning("執行中，無法封存。 Running; stop it first.")
                elif st.button("確認封存 Confirm", key=f"arch_{proj['folder']}"):
                    dest = archive_project(proj["path"])
                    if current and os.path.abspath(current) == os.path.abspath(proj["path"]):
                        st.session_state.pop("project_path", None)
                    st.success(f"已移至 Moved to {dest}")
                    st.rerun()
