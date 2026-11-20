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

"""Machine-readable run status (``<project>/status.json``) for the UI."""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

STAGES: List[str] = ["outline", "literature", "figures", "sections", "refinement"]
STAGE_LABELS = {
    "outline": "Outline 大綱",
    "literature": "Literature review 文獻回顧",
    "figures": "Figures 圖表",
    "sections": "Section writing 章節撰寫",
    "refinement": "Refinement & compile 審稿修訂/編譯",
}

_lock = threading.Lock()


PIPELINE_STATUS = "status.json"
TASK_STATUS = "task_status.json"


def status_path(base_dir: str, filename: str = PIPELINE_STATUS) -> str:
    return os.path.join(base_dir, filename)


def read_status(base_dir: str, filename: str = PIPELINE_STATUS) -> Dict[str, Any]:
    path = status_path(base_dir, filename)
    if not os.path.exists(path):
        return {}
    for _ in range(3):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            time.sleep(0.05)
    return {}


def _write(base_dir: str, data: Dict[str, Any], filename: str = PIPELINE_STATUS):
    data["updated_at"] = time.time()
    path = status_path(base_dir, filename)
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: reader holds the file briefly
            time.sleep(0.05)
    os.replace(tmp, path)


class StatusWriter:
    def __init__(
        self,
        base_dir: str,
        job: str = "pipeline",
        stages: Optional[List[str]] = None,
        filename: str = PIPELINE_STATUS,
    ):
        self.base_dir = base_dir
        self.filename = filename
        os.makedirs(base_dir, exist_ok=True)
        previous = read_status(base_dir, filename)
        prev_stages = previous.get("stages", {}) if previous.get("job") == job else {}
        self.data: Dict[str, Any] = {
            "job": job,
            "state": "running",
            "pid": os.getpid(),
            "started_at": time.time(),
            "finished_at": None,
            "current_stage": None,
            "message": "",
            "error": "",
            "stages": {
                s: prev_stages.get(s, {"status": "pending"}) for s in (stages or STAGES)
            },
        }
        self.flush()

    def flush(self):
        with _lock:
            _write(self.base_dir, self.data, self.filename)

    def stage(self, name: str, status: str, message: str = "", **extra):
        with _lock:
            entry = self.data["stages"].setdefault(name, {})
            entry["status"] = status
            if message:
                entry["message"] = message
            now = time.time()
            if status == "running":
                entry["started_at"] = now
                entry.pop("ended_at", None)
                entry.pop("error", None)
                self.data["current_stage"] = name
            elif status in ("done", "failed", "skipped"):
                entry["ended_at"] = now
                if entry.get("started_at"):
                    entry["duration_sec"] = round(now - entry["started_at"], 1)
            entry.update(extra)
            _write(self.base_dir, self.data, self.filename)

    def message(self, text: str):
        with _lock:
            self.data["message"] = text
            _write(self.base_dir, self.data, self.filename)

    def finish(self, state: str = "done", error: str = "", **extra):
        with _lock:
            self.data["state"] = state
            self.data["error"] = error
            self.data["finished_at"] = time.time()
            self.data["current_stage"] = None
            self.data.update(extra)
            _write(self.base_dir, self.data, self.filename)


def pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        import psutil  # type: ignore

        return psutil.pid_exists(int(pid)) and psutil.Process(int(pid)).status() != "zombie"
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def effective_state(status: Dict[str, Any]) -> str:
    """'running' only if the recorded process is still alive."""
    state = status.get("state", "idle") if status else "idle"
    if state == "running" and not pid_alive(status.get("pid")):
        return "interrupted"
    return state
