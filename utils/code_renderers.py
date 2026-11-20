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

"""Render figures from code: matplotlib, seaborn, plotly, graphviz and Remotion.

LLM-written code runs in a separate process with a timeout (not in-process
``exec``), so concurrent figures cannot corrupt each other's matplotlib state
and a hanging script cannot block the pipeline. The code still runs with your
user's permissions: only use models and inputs you trust.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.settings import ROOT_DIR, get_setting, resolve_path

PLOT_ENGINES = ["matplotlib", "seaborn", "plotly", "remotion"]
DIAGRAM_ENGINES = ["image", "matplotlib", "graphviz", "remotion"]
CODE_LANG = {
    "matplotlib": "python",
    "seaborn": "python",
    "plotly": "python",
    "graphviz": "dot",
    "remotion": "tsx",
}
CODE_EXT = {"python": ".py", "dot": ".dot", "tsx": ".tsx"}


@dataclass
class RenderResult:
    ok: bool
    image_path: Optional[str] = None
    animation_path: Optional[str] = None
    code: str = ""
    error: str = ""
    logs: str = ""
    extra: Dict[str, str] = field(default_factory=dict)


def extract_code(text: str, langs: List[str]) -> str:
    """Pulls the first fenced block in one of ``langs`` (or any fence)."""
    for lang in langs:
        m = re.search(rf"```{lang}\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
    m = re.search(r"```[a-zA-Z0-9_+-]*\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_").lower() or "figure"


def _subprocess_env() -> dict:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["MPLBACKEND"] = "Agg"
    return env


# ---------------------------------------------------------------------------
# Python (matplotlib / seaborn / plotly)
# ---------------------------------------------------------------------------

_PY_PRELUDE = """
import os, sys, warnings
warnings.filterwarnings("ignore")
OUTPUT_PATH = os.environ["PO_OUTPUT_PATH"]
FIG_DPI = int(os.environ.get("PO_DPI", "300"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
_po_real_show = plt.show
plt.show = lambda *a, **k: None
"""

_PY_EPILOGUE = """
# ---- PaperOrchestra auto-save epilogue ----
import os as _po_os
if not _po_os.path.exists(OUTPUT_PATH):
    _saved = False
    _fig = globals().get("fig")
    try:
        import plotly.graph_objects as _po_go
        if isinstance(_fig, _po_go.Figure):
            _fig.write_image(OUTPUT_PATH, scale=3)
            _saved = True
    except ImportError:
        pass
    if not _saved:
        try:
            if hasattr(_fig, "savefig"):
                _fig.savefig(OUTPUT_PATH, dpi=FIG_DPI, bbox_inches="tight")
                _saved = True
            elif hasattr(_fig, "figure") and hasattr(_fig.figure, "savefig"):
                _fig.figure.savefig(OUTPUT_PATH, dpi=FIG_DPI, bbox_inches="tight")
                _saved = True
        except Exception:
            pass
    if not _saved and plt.get_fignums():
        plt.figure(plt.get_fignums()[-1]).savefig(OUTPUT_PATH, dpi=FIG_DPI, bbox_inches="tight")
        _saved = True
    if not _saved:
        raise SystemExit("PO_ERROR: the script produced no figure (no matplotlib figure and no plotly `fig`).")
"""


def render_python(code: str, output_path: str, timeout: Optional[int] = None, work_dir: Optional[str] = None) -> RenderResult:
    timeout = int(timeout or get_setting("plotting.code_timeout", 180))
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        os.remove(output_path)
    # LLM code sometimes hard-codes a filename; route plt.savefig(...) to OUTPUT_PATH.
    body = re.sub(
        r"\.(savefig|write_image)\(\s*(['\"])[^'\"]+\2",
        r".\1(OUTPUT_PATH",
        code,
    )
    script = _PY_PRELUDE + "\n" + body + "\n" + _PY_EPILOGUE
    work_dir = work_dir or tempfile.mkdtemp(prefix="po_plot_")
    os.makedirs(work_dir, exist_ok=True)
    script_path = os.path.join(work_dir, "_po_render_" + os.path.basename(output_path) + ".py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    env = _subprocess_env()
    env["PO_OUTPUT_PATH"] = output_path
    env["PO_DPI"] = str(get_setting("plotting.dpi", 300))
    try:
        proc = subprocess.run(
            [sys.executable, script_path],
            cwd=work_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        logs = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0 and os.path.exists(output_path):
            return RenderResult(True, image_path=output_path, code=code, logs=logs)
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        return RenderResult(False, code=code, error="\n".join(err[-25:]) or "unknown error", logs=logs)
    except subprocess.TimeoutExpired:
        return RenderResult(False, code=code, error=f"Timed out after {timeout}s")


# ---------------------------------------------------------------------------
# Graphviz
# ---------------------------------------------------------------------------


def graphviz_available() -> bool:
    return shutil.which("dot") is not None


def render_graphviz(dot_source: str, output_path: str, timeout: int = 120) -> RenderResult:
    dot = shutil.which("dot")
    if not dot:
        return RenderResult(False, code=dot_source, error="Graphviz 'dot' executable not found in PATH.")
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    dpi = int(get_setting("plotting.dpi", 300))
    try:
        proc = subprocess.run(
            [dot, "-Tpng", f"-Gdpi={dpi}", "-o", output_path],
            input=dot_source,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RenderResult(False, code=dot_source, error=f"dot timed out after {timeout}s")
    if proc.returncode == 0 and os.path.exists(output_path):
        return RenderResult(True, image_path=output_path, code=dot_source, logs=proc.stderr)
    return RenderResult(False, code=dot_source, error=(proc.stderr or "dot failed")[-2000:])


# ---------------------------------------------------------------------------
# Remotion
# ---------------------------------------------------------------------------


def remotion_project_dir() -> str:
    return resolve_path(get_setting("plotting.remotion.project_dir", "tools/remotion"))


def remotion_status() -> Dict[str, object]:
    project = remotion_project_dir()
    node = shutil.which("node")
    cli = os.path.join(project, "node_modules", "@remotion", "cli", "remotion-cli.js")
    return {
        "node": node,
        "project_dir": project,
        "installed": os.path.exists(cli),
        "cli": cli,
        "ready": bool(node) and os.path.exists(cli),
    }


_ENTRY_TEMPLATE = """// Auto-generated by PaperOrchestra. Do not edit; edit ../generated/{name}.tsx instead.
import React from "react";
import {{Composition, registerRoot}} from "remotion";
import {{Figure}} from "../generated/{name}";

const Root: React.FC = () => (
  <Composition
    id="Figure"
    component={{Figure}}
    durationInFrames={{{frames}}}
    fps={{{fps}}}
    width={{{width}}}
    height={{{height}}}
  />
);

registerRoot(Root);
"""


def render_remotion(
    tsx_code: str,
    output_path: str,
    name: str,
    render_animation: Optional[bool] = None,
    aspect_ratio: Optional[str] = None,
) -> RenderResult:
    """Renders the last frame of a Remotion composition to PNG (+ optional MP4)."""
    status = remotion_status()
    if not status["ready"]:
        return RenderResult(
            False,
            code=tsx_code,
            error=(
                "Remotion is not installed. Install Node.js 18+ and run install.bat "
                f"(or `npm install` in {status['project_dir']})."
            ),
        )
    cfg = get_setting("plotting.remotion", {}) or {}
    width, height = int(cfg.get("width", 1920)), int(cfg.get("height", 1080))
    if aspect_ratio:
        from utils.image_backends import parse_aspect_ratio

        ratio = parse_aspect_ratio(aspect_ratio)
        height = int(round(width / ratio / 2)) * 2
    fps = int(cfg.get("fps", 30))
    frames = int(cfg.get("duration_frames", 150))
    timeout = int(cfg.get("timeout", 600))
    if render_animation is None:
        render_animation = bool(cfg.get("render_animation", False))

    project = str(status["project_dir"])
    safe = _safe_name(name)
    gen_dir = os.path.join(project, "src", "generated")
    entry_dir = os.path.join(project, "src", "entries")
    os.makedirs(gen_dir, exist_ok=True)
    os.makedirs(entry_dir, exist_ok=True)
    with open(os.path.join(gen_dir, f"{safe}.tsx"), "w", encoding="utf-8") as f:
        f.write(tsx_code)
    entry = os.path.join(entry_dir, f"{safe}.tsx")
    with open(entry, "w", encoding="utf-8") as f:
        f.write(_ENTRY_TEMPLATE.format(name=safe, frames=frames, fps=fps, width=width, height=height))

    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    base_cmd = [str(status["node"]), str(status["cli"])]
    still = base_cmd + [
        "still",
        os.path.relpath(entry, project),
        "Figure",
        output_path,
        f"--frame={frames - 1}",
        "--image-format=png",
        "--scale=1",
    ]
    env = _subprocess_env()
    try:
        proc = subprocess.run(
            still, cwd=project, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return RenderResult(False, code=tsx_code, error=f"Remotion still timed out after {timeout}s")
    logs = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 or not os.path.exists(output_path):
        return RenderResult(False, code=tsx_code, error=logs[-3000:] or "remotion still failed", logs=logs)

    result = RenderResult(True, image_path=output_path, code=tsx_code, logs=logs)
    if render_animation:
        mp4_path = os.path.splitext(output_path)[0] + ".mp4"
        render = base_cmd + ["render", os.path.relpath(entry, project), "Figure", mp4_path, "--codec=h264"]
        try:
            proc2 = subprocess.run(
                render, cwd=project, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout * 3, env=env,
            )
            if proc2.returncode == 0 and os.path.exists(mp4_path):
                result.animation_path = mp4_path
            else:
                result.extra["animation_error"] = ((proc2.stderr or "") + (proc2.stdout or ""))[-2000:]
        except subprocess.TimeoutExpired:
            result.extra["animation_error"] = "Remotion render timed out"
    return result


# ---------------------------------------------------------------------------
# dispatch + LLM prompts
# ---------------------------------------------------------------------------


def render_code(engine: str, code: str, output_path: str, name: str = "figure", aspect_ratio: Optional[str] = None) -> RenderResult:
    if engine in ("matplotlib", "seaborn", "plotly"):
        return render_python(code, output_path)
    if engine == "graphviz":
        return render_graphviz(code, output_path)
    if engine == "remotion":
        return render_remotion(code, output_path, name, aspect_ratio=aspect_ratio)
    return RenderResult(False, code=code, error=f"Unknown code engine '{engine}'")


def engine_available(engine: str) -> bool:
    if engine in ("matplotlib", "image"):
        return True
    if engine == "seaborn":
        try:
            import seaborn  # noqa: F401
            return True
        except ImportError:
            return False
    if engine == "plotly":
        try:
            import plotly  # noqa: F401
            import kaleido  # noqa: F401
            return True
        except ImportError:
            return False
    if engine == "graphviz":
        return graphviz_available()
    if engine == "remotion":
        return bool(remotion_status()["ready"])
    return False


def code_generation_prompt(engine: str, task_name: str, figure_description: str, aspect_ratio: str = "16:9") -> str:
    """Instruction for the LLM that writes rendering code for ``engine``."""
    kind = "statistical plot" if task_name == "plot" else "scientific diagram (method overview / pipeline figure)"
    common = (
        f"Create a publication-quality {kind} for an academic paper, following this detailed description:\n"
        f"{figure_description}\n\n"
        f"Target aspect ratio: {aspect_ratio}. Do NOT put a figure title or the caption inside the image. "
        "Use a clean white background, readable font sizes, and a colour-blind-friendly palette.\n"
    )
    if engine == "matplotlib":
        extra = "" if task_name == "plot" else (
            "Draw the diagram with matplotlib primitives (matplotlib.patches FancyBboxPatch/Rectangle/Circle, "
            "FancyArrowPatch / annotate arrows, ax.text). Turn the axes off and set equal-ish limits.\n"
        )
        return common + extra + (
            "Write a single self-contained Python script using matplotlib (numpy allowed). "
            "Hard-code all data values in the script. Do not read files. Do not call plt.show(). "
            "Save the figure with plt.savefig(OUTPUT_PATH, dpi=FIG_DPI, bbox_inches='tight') "
            "(OUTPUT_PATH and FIG_DPI are predefined variables).\n"
            "Return only the code in a ```python block."
        )
    if engine == "seaborn":
        return common + (
            "Write a single self-contained Python script using seaborn (import seaborn as sns) on top of "
            "matplotlib, with pandas DataFrames built from hard-coded data. Use sns.set_theme(style='whitegrid', "
            "context='paper') or similar. Do not read files. Do not call plt.show(). "
            "Save with plt.savefig(OUTPUT_PATH, dpi=FIG_DPI, bbox_inches='tight') "
            "(OUTPUT_PATH and FIG_DPI are predefined variables).\n"
            "Return only the code in a ```python block."
        )
    if engine == "plotly":
        return common + (
            "Write a single self-contained Python script using plotly (plotly.graph_objects or plotly.express) "
            "with hard-coded data. Use template='simple_white'. Assign the final figure to a variable named `fig` "
            "and call fig.write_image(OUTPUT_PATH, scale=3) (OUTPUT_PATH is predefined). Do not call fig.show().\n"
            "Return only the code in a ```python block."
        )
    if engine == "graphviz":
        return common + (
            "Write a Graphviz DOT graph (digraph) that draws this diagram. Use rankdir=LR unless the description "
            "implies a vertical flow, node shape=box with style=\"rounded,filled\", pastel fillcolors, fontname="
            "\"Helvetica\", and clusters (subgraph cluster_x) for grouped stages.\n"
            "Return only the DOT code in a ```dot block."
        )
    if engine == "remotion":
        return common + (
            "Write a Remotion (React + TypeScript) component that draws this figure and animates it in.\n"
            "Requirements:\n"
            "- A single TSX module that exports `export const Figure: React.FC = () => {...}`.\n"
            "- Import only from 'react' and 'remotion' (AbsoluteFill, useCurrentFrame, useVideoConfig, "
            "interpolate, spring, Easing, Sequence). No external assets, fonts, network or files.\n"
            "- Draw with inline SVG and/or absolutely positioned divs; use the composition width/height from "
            "useVideoConfig() for layout.\n"
            "- Elements may animate in, but by the LAST frame (durationInFrames - 1) the complete, final figure "
            "must be fully visible and static, because that frame is exported as the paper figure.\n"
            "- White background (AbsoluteFill style={{backgroundColor: 'white'}}), large legible text (>= 28px).\n"
            "Return only the code in a ```tsx block."
        )
    raise ValueError(f"No code prompt for engine '{engine}'")


def fix_code_prompt(engine: str, code: str, error: str) -> str:
    lang = CODE_LANG.get(engine, "")
    return textwrap.dedent(
        f"""\
        The following {engine} code failed to render.

        Error output:
        {error[-3000:]}

        Code:
        ```{lang}
        {code}
        ```

        Fix the code so that it renders successfully while keeping the same figure content.
        Keep the same output conventions as before. Return only the corrected code in a ```{lang} block."""
    )
