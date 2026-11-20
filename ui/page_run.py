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
import time

import streamlit as st

from ui_common import (
    STATE_BADGE,
    fmt_time,
    job_running,
    latest_log,
    launch_task,
    project_meta,
    read_text,
    require_project,
    stop_job,
    tail_file,
)
from utils.pdf_utils import latex_available
from utils.run_status import (
    PIPELINE_STATUS,
    STAGE_LABELS,
    STAGES,
    TASK_STATUS,
    effective_state,
    read_status,
)


def _preflight(project: str, meta: dict) -> list:
    issues = []
    raw = os.path.join(project, "raw_materials")
    if not read_text(os.path.join(raw, meta["idea_filename"])).strip():
        issues.append(f"缺少 Idea 檔 Missing idea file `{meta['idea_filename']}`")
    if not read_text(os.path.join(raw, meta["experimental_log_filename"])).strip():
        issues.append(f"缺少實驗紀錄 Missing experimental log `{meta['experimental_log_filename']}`")
    if not meta.get("use_plotting"):
        fig_dir = os.path.join(raw, "figures")
        if not os.path.isdir(fig_dir) or not any(
            f.lower().endswith((".png", ".jpg", ".jpeg", ".pdf")) for f in os.listdir(fig_dir)
        ):
            issues.append("未開啟自動作圖且沒有自備圖片 Figure generation is off and no figures were provided")
    return issues


@st.fragment(run_every=2)
def _live_status(project: str):
    status = read_status(project, PIPELINE_STATUS)
    task = read_status(project, TASK_STATUS)
    running = job_running(project)

    state = effective_state(status)
    st.markdown(
        f"**管線狀態 Pipeline:** `{state}`"
        + (f" · 開始 started {fmt_time(status.get('started_at'))}" if status.get("started_at") else "")
        + (f" · 結束 finished {fmt_time(status.get('finished_at'))}" if status.get("finished_at") else "")
    )
    stages = status.get("stages", {})
    cols = st.columns(len(STAGES))
    for col, name in zip(cols, STAGES):
        info = stages.get(name, {"status": "pending"})
        s = info.get("status", "pending")
        if s == "running" and state != "running":
            s = "failed"
        dur = info.get("duration_sec")
        if s == "running" and info.get("started_at"):
            dur = round(time.time() - info["started_at"], 0)
        with col.container(border=True):
            st.markdown(f"{STATE_BADGE.get(s, '⚪')} **{STAGE_LABELS[name]}**")
            st.caption(f"{s}" + (f" · {dur:.0f}s" if dur else ""))
            if info.get("message"):
                st.caption(info["message"][:200])
            if info.get("error"):
                st.caption(f"❌ {info['error'][:200]}")
    if status.get("error"):
        st.error(status["error"])

    if task:
        tstate = effective_state(task)
        msg = task.get("message") or ""
        line = f"**目前任務 Task:** `{task.get('job')}` → `{tstate}` {msg}"
        if tstate == "failed" and task.get("error"):
            st.error(line + f"\n\n{task['error']}")
        elif tstate == "done":
            st.success(line)
        else:
            st.info(line)

    log_path = latest_log(project)
    st.markdown(f"**日誌 Log:** `{os.path.basename(log_path) if log_path else '-'}`" + (" · 🔄 執行中 running" if running else ""))
    text = tail_file(log_path, 25000)
    st.code(text[-25000:] or "(尚無日誌 no log yet)", language="text", height=420)


def render():
    project = require_project()
    if not project:
        return
    meta = project_meta(project)
    st.header(f"▶️ 執行與狀態 Run & status — {meta.get('name')}")

    running = job_running(project)
    issues = _preflight(project, meta)
    if not latex_available():
        st.warning(
            "找不到 pdflatex/bibtex：會跳過審稿修訂與 PDF 編譯，只產生 LaTeX 草稿（仍可匯出 DOCX/MD）。 "
            "pdflatex/bibtex not found: refinement and PDF compilation will be skipped. Install MiKTeX or TeX Live."
        )
    for issue in issues:
        st.error(issue)

    c1, c2, c3 = st.columns([2, 3, 1])
    with c1:
        if st.button("🚀 完整執行 Run full pipeline", type="primary", disabled=bool(running or issues), width="stretch"):
            launch_task(project, ["run"], "pipeline")
            st.rerun()
    with c2:
        with st.popover("⏯️ 從指定階段執行 Run selected stages", width="stretch", disabled=bool(running)):
            start = st.selectbox("開始 Start", STAGES, format_func=lambda s: STAGE_LABELS[s], key="run_start")
            end = st.selectbox("結束 End", STAGES, index=len(STAGES) - 1, format_func=lambda s: STAGE_LABELS[s], key="run_end")
            st.caption(
                "例如修改大綱後從 literature 開始；更換圖片後從 sections 開始。 "
                "E.g. after editing the outline start at literature; after replacing figures start at sections."
            )
            if st.button("開始 Start", disabled=bool(issues) or STAGES.index(start) > STAGES.index(end)):
                launch_task(project, ["run", "--start_stage", start, "--end_stage", end], f"pipeline_{start}-{end}")
                st.rerun()
    with c3:
        if st.button("⏹️ 停止 Stop", disabled=not running, width="stretch"):
            st.toast(stop_job(project))
            st.rerun()

    st.divider()
    _live_status(project)
