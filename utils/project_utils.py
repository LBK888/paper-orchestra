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

"""Projects: one folder per paper (= the pipeline's base_dir) with project.json."""

import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from typing import Dict, List, Optional

from utils.run_status import PIPELINE_STATUS, TASK_STATUS, effective_state, read_status
from utils.settings import ROOT_DIR, get_setting, resolve_path

PROJECT_FILE = "project.json"
ZIP_EXCLUDES = ("content_refinement_workdir/pdf_screenshots", "figures/work", "__pycache__")


def projects_root() -> str:
    path = resolve_path(get_setting("ui.projects_dir", "projects"))
    os.makedirs(path, exist_ok=True)
    return path


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE).strip("_")
    return slug or datetime.now().strftime("project_%Y%m%d_%H%M%S")


def default_project(name: str) -> Dict:
    models = get_setting("llm.default_models", {}) or {}
    return {
        "name": name,
        "created_at": time.time(),
        "updated_at": time.time(),
        "template": "cvpr2025",
        "idea_filename": "idea.md",
        "experimental_log_filename": "experimental_log.md",
        "use_plotting": True,
        "research_cutoff": datetime.now().strftime("%Y-%m"),
        "models": {
            "writer": models.get("writer"),
            "reflection": models.get("reflection"),
            "plotting": models.get("plotting"),
            "search": models.get("search"),
            "revision": models.get("revision"),
        },
        "image_backend": get_setting("image.default_backend"),
        "plot_engine": get_setting("plotting.plot_engine", "matplotlib"),
        "diagram_engine": get_setting("plotting.diagram_engine", "image"),
        "search_backend": get_setting("literature.search_backend", "auto"),
        "max_reflections": int(get_setting("pipeline.max_reflections", 3)),
        "plotting_max_critic_rounds": int(get_setting("pipeline.plotting_max_critic_rounds", 3)),
        "notes": "",
    }


def create_project(name: str, root: Optional[str] = None) -> str:
    root = root or projects_root()
    path = os.path.join(root, slugify(name))
    if os.path.exists(path):
        raise FileExistsError(f"Project folder already exists: {path}")
    os.makedirs(os.path.join(path, "raw_materials", "figures"))
    save_project(path, default_project(name))
    return path


def load_project(path: str) -> Dict:
    file = os.path.join(path, PROJECT_FILE)
    data = default_project(os.path.basename(path))
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        models = {**data["models"], **(saved.get("models") or {})}
        data.update(saved)
        data["models"] = models
    return data


def save_project(path: str, data: Dict) -> None:
    data = dict(data)
    data["updated_at"] = time.time()
    with open(os.path.join(path, PROJECT_FILE), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def project_state(path: str) -> str:
    task = read_status(path, TASK_STATUS)
    if effective_state(task) == "running":
        return f"running ({task.get('job')})"
    status = read_status(path, PIPELINE_STATUS)
    state = effective_state(status)
    if state == "idle" and os.path.exists(os.path.join(path, "final_paper.pdf")):
        return "done"
    return state


def list_projects(root: Optional[str] = None) -> List[Dict]:
    root = root or projects_root()
    out = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path) or name.startswith("."):
            continue
        if not os.path.exists(os.path.join(path, PROJECT_FILE)) and not os.path.isdir(os.path.join(path, "raw_materials")):
            continue
        meta = load_project(path)
        out.append(
            {
                "name": meta.get("name", name),
                "folder": name,
                "path": path,
                "updated_at": meta.get("updated_at") or os.path.getmtime(path),
                "state": project_state(path),
                "has_pdf": os.path.exists(os.path.join(path, "final_paper.pdf")),
            }
        )
    out.sort(key=lambda p: p["updated_at"], reverse=True)
    return out


def export_project_zip(path: str, out_path: Optional[str] = None, include_heavy: bool = False) -> str:
    out_path = out_path or os.path.join(tempfile.gettempdir(), f"{os.path.basename(path)}.paperorchestra.zip")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(path):
            rel_root = os.path.relpath(root, path).replace("\\", "/")
            if not include_heavy and any(rel_root.startswith(x) for x in ZIP_EXCLUDES):
                continue
            for name in files:
                if name.endswith((".tmp", ".aux")):
                    continue
                full = os.path.join(root, name)
                zf.write(full, os.path.join(os.path.basename(path), os.path.relpath(full, path)))
    return out_path


def import_project_zip(zip_path: str, root: Optional[str] = None) -> str:
    root = root or projects_root()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        top = {n.split("/")[0] for n in names if n.strip("/")}
        for n in names:
            if n.startswith("/") or ".." in n.replace("\\", "/").split("/"):
                raise ValueError(f"Unsafe path in archive: {n}")
        tmp = tempfile.mkdtemp(prefix="po_import_")
        zf.extractall(tmp)
    src = os.path.join(tmp, top.pop()) if len(top) == 1 else tmp
    base = slugify(os.path.basename(src) if len(top) == 0 else "imported_project")
    dest = os.path.join(root, base)
    i = 2
    while os.path.exists(dest):
        dest = os.path.join(root, f"{base}_{i}")
        i += 1
    shutil.move(src, dest)
    for status_file in (PIPELINE_STATUS, TASK_STATUS):
        sp = os.path.join(dest, status_file)
        if os.path.exists(sp):
            with open(sp, "r", encoding="utf-8") as f:
                st = json.load(f)
            if st.get("state") == "running":
                st["state"] = "interrupted"
                with open(sp, "w", encoding="utf-8") as f:
                    json.dump(st, f, indent=2)
    if not os.path.exists(os.path.join(dest, PROJECT_FILE)):
        save_project(dest, default_project(os.path.basename(dest)))
    return dest


def archive_project(path: str) -> str:
    """Moves a project into <projects>/.trash (recoverable) instead of deleting."""
    trash = os.path.join(os.path.dirname(path), ".trash")
    os.makedirs(trash, exist_ok=True)
    dest = os.path.join(trash, f"{os.path.basename(path)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.move(path, dest)
    return dest


def available_templates() -> List[str]:
    tdir = os.path.join(ROOT_DIR, "templates")
    return sorted(
        d for d in os.listdir(tdir)
        if os.path.isdir(os.path.join(tdir, d)) and os.path.exists(os.path.join(tdir, d, "template.tex"))
    )
