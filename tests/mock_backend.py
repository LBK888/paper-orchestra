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

"""In-process mock backend for tests.

Serves OpenAI-compatible ``/v1/chat/completions`` + ``/v1/models`` +
``/v1/images/generations``, Ollama ``/api/chat`` + ``/api/tags``, ComfyUI
``/prompt`` ``/history`` ``/view`` ``/system_stats``, and a generic ``/gen-image``
JSON API. Chat replies are picked by matching the prompt text, so the real
agents can run end to end without any model.
"""

import base64
import io
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Tuple

from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REMOTION_SAMPLE = os.path.join(ROOT, "tools", "remotion", "src", "SampleFigure.tsx")


def png_bytes(text: str = "mock", color=(70, 130, 180)) -> bytes:
    img = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 600, 320], outline=color, width=6)
    draw.text((60, 160), text, fill=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


OUTLINE = {
    "plotting_plan": [
        {"figure_id": "fig_results_bar", "title": "Main results", "plot_type": "plot",
         "data_source": "experimental_log.md", "objective": "Bar chart of accuracy per method", "aspect_ratio": "16:9"},
        {"figure_id": "fig_method_overview", "title": "Method overview", "plot_type": "diagram",
         "data_source": "idea.md", "objective": "Pipeline diagram of the method", "aspect_ratio": "16:9"},
    ],
    "intro_related_work_plan": {
        "introduction_strategy": {
            "hook_hypothesis": "Efficient attention matters.",
            "problem_gap_hypothesis": "Quadratic cost.",
            "search_directions": ["efficient transformers survey"],
        },
        "related_work_strategy": {
            "overview": "x",
            "subsections": [{
                "subsection_title": "2.1 Efficient attention", "methodology_cluster": "sparse",
                "sota_investigation_mission": "m", "limitation_hypothesis": "h",
                "limitation_search_queries": ["linear attention transformers"],
            }],
        },
    },
    "section_plan": [
        {"section_title": "3. Method", "subsections": [
            {"subsection_title": "3.1 Model", "content_bullets": ["describe"],
             "citation_hints": ["Vaswani et al. (Attention Is All You Need)"]}]},
    ],
}

PAPER = r"""\documentclass{article}
\usepackage{graphicx}
\title{Mock Paper on Efficient Attention}
\begin{document}
\maketitle
\begin{abstract}
We propose a mock method that is efficient.
\end{abstract}
\section{Introduction}
Transformers \cite{Vaswani2017AttentionAll} are popular.
\section{Method}
Our method uses \textbf{linear attention}.
\begin{figure}[t]
\centering
\includegraphics[width=\linewidth]{figures/fig_results_bar.png}
\caption{Main results.}
\label{fig:res}
\end{figure}
\section{Experiments}
We reach 80.3\% accuracy (Fig.~\ref{fig:res}).
\section{Conclusion}
Done.
\bibliographystyle{plain}
\bibliography{references}
\end{document}
"""

PLOT_CODE = """```python
import matplotlib.pyplot as plt
methods = ['A', 'B', 'Ours']
acc = [71.2, 75.9, 80.3]
fig, ax = plt.subplots(figsize=(6, 3.4))
ax.bar(methods, acc, color=['#4C78A8', '#F58518', '#54A24B'])
ax.set_ylabel('Accuracy (%)')
plt.savefig('result.png', dpi=FIG_DPI, bbox_inches='tight')
```"""

DIAGRAM_CODE = """```python
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
fig, ax = plt.subplots(figsize=(8, 3))
for i, name in enumerate(['Input', 'Encoder', 'Linear Attn', 'Output']):
    ax.add_patch(FancyBboxPatch((i * 2.2, 0.5), 1.8, 1, boxstyle='round,pad=0.1', fc='#dbe9f6', ec='#4C78A8'))
    ax.text(i * 2.2 + 0.9, 1.0, name, ha='center', va='center')
ax.set_xlim(-0.3, 8.8); ax.set_ylim(0, 2); ax.axis('off')
```"""

REVIEW = {
    "Summary": "ok", "Strengths": "s", "Weaknesses": "w", "Questions": "q",
    "Originality": 3, "Quality": 3, "Clarity": 3, "Significance": 3, "Soundness": 3,
    "Presentation": 3, "Contribution": 3, "Overall": 6, "Confidence": 4,
}


def chat_reply(p: str) -> str:
    """Canned replies keyed on distinctive phrases of each agent's prompt."""
    if "Reply with exactly: OK" in p:
        return "<think>reasoning that must be stripped</think>OK"
    if '"plotting_plan", "intro_related_work_plan", and "section_plan"' in p:
        return "Here is the outline:\n```json\n" + json.dumps(OUTLINE) + "\n```"
    if "selecting the ONE academic paper" in p:
        return '{"index": 0, "reason": "exact match"}'
    if "building the reference list" in p:
        return '{"selected": [{"index": 0, "reason": "relevant"}, {"index": 1, "reason": "relevant"}]}'
    if "Identify the SPECIFIC academic paper" in p or "Find 10-15 highly relevant" in p:
        return ('```json\n{"section_name": "x", "candidates": [{"title": "Attention Is All You Need", '
                '"year": 2017, "reason": "foundational"}]}\n```')
    if "Generate the LaTeX for Introduction and Related Work" in p:
        return "```latex\n" + PAPER.split("\\section{Method}")[0] + "\\section{Method}\nTODO\n\\end{document}\n```"
    if "Target Plot for Critique" in p or "Target Diagram for Critique" in p:
        return '```json\n{"critic_suggestions": "No changes needed.", "revised_description": "No changes needed."}\n```'
    if "provide the final caption" in p:
        return "Accuracy of each method on the benchmark."
    if "matplotlib primitives" in p:
        return DIAGRAM_CODE
    if "Write a single self-contained Python script" in p or "Use python matplotlib" in p or "failed to render" in p:
        return PLOT_CODE
    if "Write a Remotion" in p:
        with open(REMOTION_SAMPLE, "r", encoding="utf-8") as f:
            return "```tsx\n" + f.read() + "\n```"
    if "Rewrite the following figure description as a single prompt" in p:
        return "flat vector diagram, boxes and arrows, white background"
    if "AUTHOR INSTRUCTION" in p:
        if "PART TO REVISE" in p:
            part = p.split("--- PART TO REVISE", 1)[1].split("---\n", 1)[1].split("\n\nOutput first", 1)[0]
            return ('```json\n{"summary": "strengthened"}\n```\n```latex\n'
                    + part.replace("efficient", "very efficient (revised)") + "\n```")
        return '```json\n{"summary": "full"}\n```\n```latex\n' + PAPER.replace("Done.", "Done (revised).") + "\n```"
    if "REFLECTION ITERATION" in p:  # content refinement agent (only runs when LaTeX is installed)
        return '```json\n{"addressed_weaknesses": []}\n```\n```latex\n' + PAPER + "\n```"
    if "for formatting issues" in p:  # VLM formatting review
        return '```json\n{"figure_and_tables": {}, "other_issues": []}\n```'
    if "Detailed Description" in p or "Style Guidelines" in p or "Now, based on the following" in p:
        return "A bar chart with three bars (A=71.2, B=75.9, Ours=80.3), blue/orange/green, y-axis Accuracy (%)."
    if "Overall" in p and "review" in p.lower():
        return "```json\n" + json.dumps(REVIEW) + "\n```"
    return "```latex\n" + PAPER + "\n```"


class MockBackend:
    """Thread-hosted HTTP server; ``requests`` holds every POST for assertions."""

    def __init__(self):
        self.requests: List[dict] = []
        self.comfy_jobs: dict = {}
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _png(self, data: bytes):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split("?")[0]
                if path == "/v1/models":
                    return self._json({"data": [{"id": "mock-model"}, {"id": "mock-vision"}]})
                if path == "/api/tags":
                    return self._json({"models": [{"name": "qwen3:mock"}]})
                if path == "/system_stats":
                    return self._json({"system": {"comfyui_version": "mock-0.3"}})
                if path.startswith("/object_info/"):
                    return self._json({"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["mock.safetensors"]]}}}})
                if path.startswith("/history/"):
                    pid = path.rsplit("/", 1)[1]
                    if pid in backend.comfy_jobs:
                        return self._json({pid: {
                            "status": {"completed": True, "status_str": "success"},
                            "outputs": {"9": {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}},
                        }})
                    return self._json({})
                if path == "/view":
                    return self._png(png_bytes("comfyui"))
                self._json({"error": "not found"}, 404)

            def do_POST(self):
                path = self.path.split("?")[0]
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                backend.requests.append({"path": path, "body": body, "headers": dict(self.headers)})

                if path == "/v1/chat/completions":
                    if body.get("modalities"):
                        url = "data:image/png;base64," + base64.b64encode(png_bytes("openrouter")).decode()
                        message = {"role": "assistant", "content": "",
                                   "images": [{"type": "image_url", "image_url": {"url": url}}]}
                    else:
                        text = ""
                        for m in body.get("messages", []):
                            content = m.get("content")
                            if isinstance(content, str):
                                text += content + "\n"
                            else:
                                text += "".join(c.get("text", "") + "\n" for c in content if c.get("type") == "text")
                        message = {"role": "assistant", "content": chat_reply(text)}
                    return self._json({
                        "id": "x", "object": "chat.completion", "created": 0, "model": body.get("model"),
                        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    })
                if path == "/api/chat":
                    text = "\n".join(m.get("content", "") for m in body.get("messages", []))
                    return self._json({"model": body["model"], "done": True,
                                       "message": {"role": "assistant", "content": chat_reply(text)}})
                if path == "/v1/images/generations":
                    return self._json({"created": 0, "data": [{"b64_json": base64.b64encode(png_bytes("images api")).decode()}]})
                if path == "/prompt":
                    pid = str(uuid.uuid4())
                    backend.comfy_jobs[pid] = body["prompt"]
                    return self._json({"prompt_id": pid, "number": 1})
                if path == "/gen-image":
                    b64 = base64.b64encode(png_bytes(str(body.get("text", "http")))).decode()
                    return self._json({"result": {"images": [{"base64": b64}]}})
                self._json({"error": "not found"}, 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "MockBackend":
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def last(self, path: str, **match) -> dict:
        """Most recent request to ``path`` whose body contains ``match`` items."""
        for req in reversed(self.requests):
            if req["path"] == path and all(req["body"].get(k) == v for k, v in match.items()):
                return req
        raise AssertionError(f"no request to {path} matching {match}")


def build_test_settings(base_url: str, projects_dir: str, mcp_server_script: str, python: str) -> dict:
    """Settings overrides that point every provider/backend at the mock.

    ``api_key_env`` is nulled so a developer's real keys in .env are never sent.
    """
    v1 = base_url + "/v1"
    mcp_common = {"transport": "stdio", "command": python, "args": [mcp_server_script], "timeout": 120}
    return {
        "llm": {
            "default_provider": "llamacpp",
            "default_models": {
                "writer": "llamacpp:mock-model",
                "reflection": "llamacpp:mock-model",
                "plotting": "vllm:mock-model",
                "search": "ollama:qwen3:mock",
                "fast": "lmstudio:mock-model",
                "revision": "openrouter:mock/model",
            },
            "providers": {
                "ollama": {"base_url": base_url, "num_ctx": 16384},
                "llamacpp": {"base_url": v1},
                "vllm": {"base_url": v1, "api_key_env": None, "api_key": "EMPTY", "supports_vision": True},
                "lmstudio": {"base_url": v1},
                "openrouter": {"base_url": v1, "api_key_env": None, "api_key": "test-key"},
                "openai": {"base_url": v1, "api_key_env": None, "api_key": "test-key"},
                "custom": {"base_url": v1, "api_key_env": None, "api_key": "test-key"},
            },
        },
        "image": {
            "default_backend": "comfyui",
            "comfyui": {"base_url": base_url},
            "mcp_servers": {
                "mock": {**mcp_common, "tool": "generate_image", "prompt_arg": "prompt",
                         "extra_args": {"width": "{{WIDTH}}", "height": "{{HEIGHT}}"}},
                "mock-text": {**mcp_common, "tool": "generate_image_url", "prompt_arg": "prompt"},
            },
            "http_apis": {
                "mockapi": {
                    "url": base_url + "/gen-image",
                    "method": "POST",
                    "headers": {"Authorization": "Bearer ${PO_TEST_HTTP_KEY}"},
                    "body": {"text": "{{PROMPT}}", "w": "{{WIDTH}}", "h": "{{HEIGHT}}"},
                    "response_path": "result.images.0.base64",
                }
            },
        },
        "plotting": {"plot_engine": "matplotlib", "diagram_engine": "matplotlib"},
        "literature": {"search_backend": "semantic_scholar", "s2_min_interval_sec": 0},
        "pipeline": {"max_pipeline_retries": 1},
        "ui": {"projects_dir": projects_dir},
    }
