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

"""Shared helpers for the Streamlit UI: background jobs, logs, pickers."""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.llm_providers import get_providers  # noqa: E402
from utils.project_utils import load_project, save_project  # noqa: E402
from utils.run_status import (  # noqa: E402
    PIPELINE_STATUS,
    TASK_STATUS,
    effective_state,
    pid_alive,
    read_status,
)

LAUNCH_FILE = ".job_launch.json"
TASKS_SCRIPT = os.path.join(ROOT, "po_tasks.py")


# ---------------------------------------------------------------------------
# project selection
# ---------------------------------------------------------------------------


def current_project() -> Optional[str]:
    path = st.session_state.get("project_path")
    if path and os.path.isdir(path):
        return path
    return None


def require_project() -> Optional[str]:
    path = current_project()
    if not path:
        st.info("請先在「專案 Projects」頁面建立或開啟一個專案。 Open or create a project first.")
    return path


def project_meta(path: str) -> Dict:
    return load_project(path)


def update_project(path: str, **changes) -> Dict:
    meta = load_project(path)
    meta.update(changes)
    save_project(path, meta)
    return meta


# ---------------------------------------------------------------------------
# background jobs
# ---------------------------------------------------------------------------


def _launch_record(project: str) -> Dict:
    path = os.path.join(project, LAUNCH_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def job_running(project: str) -> Optional[Dict]:
    """Returns the launch record if a job process for this project is alive."""
    rec = _launch_record(project)
    if rec and pid_alive(rec.get("pid")):
        return rec
    for fname in (PIPELINE_STATUS, TASK_STATUS):
        status = read_status(project, fname)
        if effective_state(status) == "running":
            return {"pid": status.get("pid"), "job": status.get("job"), "log": rec.get("log")}
    return None


def launch_task(project: str, args: List[str], label: str) -> Optional[int]:
    """Starts ``python po_tasks.py <args> --project <project>`` in the background."""
    if job_running(project):
        st.warning("此專案已有工作在執行中。 A job is already running for this project.")
        return None
    logs_dir = os.path.join(project, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(logs_dir, f"{stamp}_{label}.log")
    cmd = [sys.executable, "-u", TASKS_SCRIPT] + args + ["--project", project]
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    log_file = open(log_path, "w", encoding="utf-8")
    log_file.write(f"$ {' '.join(cmd)}\n\n")
    log_file.flush()
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT, env=env, **kwargs)
    with open(os.path.join(project, LAUNCH_FILE), "w", encoding="utf-8") as f:
        json.dump({"pid": proc.pid, "job": label, "log": log_path, "cmd": cmd, "started_at": time.time()}, f, indent=2)
    st.session_state["last_log"] = log_path
    return proc.pid


def stop_job(project: str) -> str:
    rec = job_running(project)
    if not rec or not rec.get("pid"):
        return "沒有執行中的工作。 No running job."
    pid = int(rec["pid"])
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            os.kill(pid, signal.SIGTERM)
    for fname in (PIPELINE_STATUS, TASK_STATUS):
        status = read_status(project, fname)
        if status.get("state") == "running":
            status["state"] = "stopped"
            status["error"] = "Stopped by user"
            with open(os.path.join(project, fname), "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
    return f"已停止 PID {pid}。 Stopped."


def latest_log(project: str) -> Optional[str]:
    rec = _launch_record(project)
    if rec.get("log") and os.path.exists(rec["log"]):
        return rec["log"]
    logs_dir = os.path.join(project, "logs")
    if os.path.isdir(logs_dir):
        files = sorted(
            (os.path.join(logs_dir, f) for f in os.listdir(logs_dir) if f.endswith(".log")),
            key=os.path.getmtime,
        )
        if files:
            return files[-1]
    return None


def tail_file(path: Optional[str], max_bytes: int = 30000) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read().decode("utf-8", errors="replace")
    return data


# ---------------------------------------------------------------------------
# widgets
# ---------------------------------------------------------------------------

IMAGE_KINDS = ["gemini", "openai", "openrouter", "custom", "comfyui", "mcp", "http"]


def split_spec(spec: Optional[str], providers: List[str]):
    spec = spec or ""
    if ":" in spec:
        prefix, rest = spec.split(":", 1)
        if prefix in providers:
            return prefix, rest
    return (providers[0] if providers else ""), spec


def model_picker(label: str, current: Optional[str], key: str, help: Optional[str] = None) -> str:
    """Provider select + model text (with suggestions fetched in Settings)."""
    providers = list(get_providers().keys())
    prov, model = split_spec(current, providers)
    c1, c2 = st.columns([1, 2])
    with c1:
        prov = st.selectbox(
            f"{label} · provider",
            providers,
            index=providers.index(prov) if prov in providers else 0,
            key=f"{key}_prov",
            help=help,
        )
    suggestions = st.session_state.get("model_lists", {}).get(prov, [])
    with c2:
        if suggestions:
            options = sorted(set(suggestions + ([model] if model else [])))
            model = st.selectbox(
                f"{label} · model",
                options,
                index=options.index(model) if model in options else 0,
                key=f"{key}_model_sel_{prov}",
                accept_new_options=True,
            )
        else:
            model = st.text_input(f"{label} · model", value=model, key=f"{key}_model_{prov}")
    return f"{prov}:{model}" if model else ""


def image_backend_picker(label: str, current: Optional[str], key: str) -> str:
    from utils.settings import get_setting

    current = current or get_setting("image.default_backend", "")
    kind, _, target = current.partition(":")
    if kind not in IMAGE_KINDS:
        kind, target = "gemini", current
    c1, c2 = st.columns([1, 2])
    with c1:
        kind = st.selectbox(f"{label} · backend", IMAGE_KINDS, index=IMAGE_KINDS.index(kind), key=f"{key}_kind")
    with c2:
        if kind == "mcp":
            servers = list((get_setting("image.mcp_servers", {}) or {}).keys())
            target = st.selectbox("MCP server", servers or [""], index=servers.index(target) if target in servers else 0, key=f"{key}_mcp")
        elif kind == "http":
            apis = list((get_setting("image.http_apis", {}) or {}).keys())
            target = st.selectbox("HTTP API", apis or [""], index=apis.index(target) if target in apis else 0, key=f"{key}_http")
        elif kind == "comfyui":
            target = st.text_input("Workflow (blank = default from Settings)", value=target, key=f"{key}_comfy")
        else:
            hint = {
                "gemini": "gemini-3-pro-image-preview",
                "openai": "gpt-image-1",
                "openrouter": "google/gemini-2.5-flash-image",
                "custom": "model name",
            }.get(kind, "")
            target = st.text_input("Image model", value=target or hint, key=f"{key}_model_{kind}")
    return f"{kind}:{target}" if target or kind == "comfyui" else kind


STATE_BADGE = {
    "pending": "⚪",
    "running": "🔄",
    "done": "✅",
    "failed": "❌",
    "skipped": "⏭️",
}


def fmt_time(ts: Optional[float]) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def read_text(path: str, default: str = "") -> str:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
