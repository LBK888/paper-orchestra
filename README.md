# <div align="center">🎻 PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing</div>
<div align="center">Yiwen Song<sup>1</sup>, Yale Song<sup>1</sup>, Tomas Pfister<sup>1</sup>, and Jinsung Yoon<sup>1</sup></div>
<div align="center"><sup>1</sup>Google Cloud AI Research</div>
<br>
<div align="center"><b>English</b> | <a href="README_TW.md">繁體中文（台灣）</a></div>
<br>

PaperOrchestra is a multi-agent framework for automated AI research paper writing. It flexibly transforms unconstrained pre-writing materials (ideas and experimental logs) into submission-ready LaTeX manuscripts, including comprehensive literature synthesis and generated visuals, such as plots and conceptual diagrams.

Acting like an orchestrated team of specialized agents, it handles outline generation, literature review, section writing, content refinement, and plotting to close the gap between raw research materials and submission-ready papers.

<div align="center">
  <img src="assets/overview.png" alt="PaperOrchestra Overview" width="90%"/>
</div>

> **About this fork.** [LBK888/paper-orchestra](https://github.com/LBK888/paper-orchestra) extends the original Google Research release with support for any LLM provider (local or cloud), pluggable image generation (ComfyUI, MCP, HTTP APIs), code-based scientific plotting (matplotlib, seaborn, plotly, Graphviz, Remotion), a desktop-style web UI with human-in-the-loop revision, DOCX/Markdown export, a resumable pipeline, a Windows installer and an offline test suite.

## Contents

- [Key features](#key-features)
- [Quick start](#quick-start)
- [Writing your first paper in the UI](#writing-your-first-paper-in-the-ui)
- [Configuration](#configuration)
- [Figures](#figures)
- [Pipeline, projects and the command line](#pipeline-projects-and-the-command-line)
- [Export](#export)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)
- [Citation](#citation)

## Key features

- **Multi-agent pipeline**: specialized agents (Outline, Literature Review, Section Writing, Content Refinement, Plotting) take raw materials to a finished paper.
- **Comprehensive literature synthesis**: searches, prioritizes and cites relevant work, with a publication-date cutoff.
- **LaTeX automation**: writes into conference templates (`templates/cvpr2025`, `templates/iclr2025`, or your own).
- **Any LLM**: Gemini, OpenAI, OpenRouter, Ollama, llama.cpp, vLLM, LM Studio or any OpenAI-compatible endpoint, chosen per role (writer, reviewer, plotter, search, revision).
- **Pluggable image generation** for diagrams: Gemini, OpenAI Images, OpenRouter, local ComfyUI, any MCP server tool, or a generic HTTP API.
- **Code-based scientific figures**: matplotlib, seaborn, plotly, Graphviz and Remotion (animated React figures; the last frame becomes the paper figure, with optional MP4).
- **PaperOrchestra Studio** (web UI): projects, live run status, result inspection, manual and AI-assisted revision, settings and export.
- **Human-in-the-loop revision**: revise one section by instruction with diff, history and revert; edit LaTeX or the outline; regenerate, replace or re-code any figure.
- **Export** to PDF, Word (.docx), Markdown and a LaTeX source zip.
- **Resumable pipeline**: restart from any stage after editing inputs, the outline or figures.
- **Windows-ready**: `install.bat` checks the machine and installs everything; `start.bat` opens the UI.

## Quick start

### Requirements

| Component | Needed for | Notes |
|---|---|---|
| Python 3.10–3.13 | everything | 3.12 recommended |
| An LLM | everything | cloud API key, or a local server (Ollama, llama.cpp, vLLM, LM Studio) |
| LaTeX (MiKTeX or TeX Live) | PDF output and the review-and-refine loop | without it you still get LaTeX, DOCX and Markdown |
| Node.js 18+ | Remotion figures | optional |
| Graphviz | Graphviz diagrams | optional |
| Google Chrome | plotly static images | optional; kaleido can download one |
| Semantic Scholar API key | literature search | optional but strongly recommended (rate limits) |

### Windows

```bat
install.bat
start.bat
```

`install.bat` finds a suitable Python, creates `.venv`, installs `requirements.txt`, creates `.env` from `.env.example`, and offers (via winget) to install MiKTeX, Node.js plus the Remotion workspace, and Graphviz. Options: `install.bat /y` accepts every optional install, `install.bat /minimal` installs Python packages only.

`start.bat` launches **PaperOrchestra Studio** at http://localhost:8501 (`start.bat 8600` uses another port).

### macOS / Linux (manual)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                   # add your keys
(cd tools/remotion && npm install)                     # optional: Remotion figures
PYTHONUTF8=1 streamlit run ui/app.py
```

## Writing your first paper in the UI

1. **Settings → Keys**: add the API keys you use (stored in `.env`). For local models, check the endpoint under **Settings → LLM providers** and press **List models** / **Test**.
2. **Projects**: create a project (tick *Load the CVPR example materials* for a ready-made sample).
3. **Inputs → Materials**: write or upload the idea and the experimental log; optionally upload finished figures with captions.
4. **Inputs → Options**: pick the template, the model for each role, figure engines, the diagram image backend and the literature cutoff, then **Save options**.
5. **Run & status**: press **Run full pipeline** and watch each stage and the log update live.
6. **Results**: read the paper, outline, references, figures (with critic history and source code) and reviewer scores; optionally run an **AI review**.
7. **Revise**: ask for changes to one section, edit the LaTeX or outline, or fix individual figures, then recompile or re-run later stages.
8. **Export**: download PDF, DOCX, Markdown, the LaTeX source, or the whole project as a zip.

| Page | What it does |
|---|---|
| Projects | create, open, import / export (.zip), archive (moved to `projects/.trash`) |
| Inputs | idea and experimental-log editors, provided figures with captions, per-project models, engines, template, cutoff |
| Run & status | run everything or a stage range, stop, live stage timeline and log |
| Results | PDF pages, outline, references, figures, refinement scores, AI review, timing |
| Revise | AI revision of the whole paper or one section (diff, history, revert); direct LaTeX editing and compile; outline editing and re-run; per-figure caption / replace / exclude / regenerate / edit code and re-render |
| Export | PDF, Word, Markdown (+ media folder), LaTeX zip, project zip |
| Settings | keys, LLM providers, default models, image backends (with connection tests), plotting engines, literature and pipeline options, system check |

## Configuration

### Files

| File | Purpose |
|---|---|
| `.env` | API keys (git-ignored). See `.env.example`. Editable from **Settings → Keys**. |
| `config/settings.default.json` | shipped defaults; do not edit |
| `config/settings.json` | your overrides (git-ignored), written by the Settings page; deep-merged over the defaults |
| `projects/<name>/project.json` | per-project choices (models, template, engines, …) |

Set `PAPER_ORCHESTRA_SETTINGS=/path/to/settings.json` to use a different settings file.

Keys read from `.env`: `GEMINI_API_KEY` (or `VERTEX_AI_PROJECT` + `VERTEX_AI_LOCATION`), `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `VLLM_API_KEY`, `CUSTOM_LLM_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`, `PAPERBANANA_DIR` (optional few-shot figure references), `SMTP_EMAIL` / `SMTP_PASSWORD` (legacy demo only). Values in settings may reference variables as `${NAME}`.

### LLM providers

Model names take a provider prefix. Names without a prefix keep the original behaviour (`gpt*`, `o1`, `o3`, `o4` → OpenAI, everything else → Gemini).

| Prefix | Backend | Default endpoint |
|---|---|---|
| `gemini:` | Gemini API key or Vertex AI | — |
| `openai:` | OpenAI | `https://api.openai.com/v1` |
| `openrouter:` | OpenRouter | `https://openrouter.ai/api/v1` |
| `ollama:` | Ollama native API | `http://localhost:11434` |
| `llamacpp:` | llama.cpp `llama-server` | `http://localhost:8080/v1` |
| `vllm:` | vLLM OpenAI-compatible server | `http://localhost:8000/v1` |
| `lmstudio:` | LM Studio server | `http://localhost:1234/v1` |
| `custom:` | any OpenAI-compatible endpoint | set in Settings |

Examples: `gemini:gemini-3.1-pro-preview`, `openai:gpt-5`, `openrouter:anthropic/claude-sonnet-4.5`, `ollama:qwen3:32b`, `llamacpp:local`, `vllm:Qwen/Qwen3-32B`. More OpenAI-compatible services (DeepSeek, Groq, Together, SiliconFlow, …) can be added under **Settings → LLM providers → Add an OpenAI-compatible provider**.

Starting local servers:

```bash
ollama pull qwen3:32b                      # Ollama (server runs in the background)
llama-server -m model.gguf --port 8080 -c 32768   # llama.cpp
vllm serve Qwen/Qwen3-32B --port 8000      # vLLM
# LM Studio: load a model and start the local server
```

Per-provider settings: `base_url`, `api_key_env`, `timeout`, `max_concurrency` (Ollama, llama.cpp and LM Studio default to one request at a time, vLLM to 8), `supports_vision` (images are replaced by a note when false), Ollama `num_ctx` (context window, default 32768) and `think`, and `extra_body` for OpenAI-compatible servers (for example vLLM `{"chat_template_kwargs": {"enable_thinking": false}}`). `<think>…</think>` blocks from reasoning models are removed automatically.

Model roles (Settings → Default models, or per project): **writer** (outline, literature synthesis, sections), **reflection** (review and refinement), **plotting** (figure planning, code, critique), **search** (literature discovery), **fast** (small helper tasks such as condensing ComfyUI prompts), **revision** (manual revisions).

> The pipeline sends long prompts (whole papers plus experimental logs). Local models need a large context window (32k or more) and strong instruction following to produce valid JSON and LaTeX.

### Literature search

`--search_backend` / Settings → Literature:

| Backend | How it works |
|---|---|
| `gemini` | Gemini with Google Search grounding (original behaviour) |
| `semantic_scholar` | Semantic Scholar keyword search; the LLM picks the relevant results. Works with any model. |
| `llm` | the model recalls titles from its own knowledge; each is verified on Semantic Scholar |
| `auto` (default) | `gemini` when the search model is a Gemini model, otherwise `semantic_scholar` |

Every candidate is checked against Semantic Scholar and filtered by the research cutoff date before it can be cited.

## Figures

With figure generation on, the outline agent plans the figures and the plotting agent plans, styles, renders and critiques each one. Figures you upload in **Inputs** are merged with the generated ones; with figure generation off, only your figures are used.

### Engines

| Engine | Used for | Requires |
|---|---|---|
| `matplotlib` | plots (default) and code-drawn diagrams | — |
| `seaborn` | statistical plots | — |
| `plotly` | plots | Chrome for static export |
| `graphviz` | box-and-arrow diagrams (DOT) | Graphviz |
| `remotion` | animated React/TSX figures; last frame → PNG, optional MP4 | Node.js + `tools/remotion` |
| `image` | diagrams from an image-generation backend (default for diagrams) | a backend below |

Code written by the LLM runs in a separate Python/Node process with a timeout, gets up to two automatic fix attempts when it fails, and is saved under `<project>/figures/src/` so you can edit it and re-render from **Revise → Figures**. The code runs with your user's permissions; use models you trust.

Remotion components must `export const Figure` and import only from `react` and `remotion`; see `tools/remotion/src/SampleFigure.tsx` (`npm run studio` in `tools/remotion` previews it). Size, fps, length and MP4 output are set in **Settings → Plotting**.

### Image backends for diagrams

| Spec | Backend |
|---|---|
| `gemini:gemini-3-pro-image-preview` | Gemini native image generation (default) |
| `openai:gpt-image-1` / `custom:<model>` | OpenAI-compatible `/images/generations` |
| `openrouter:<image model>` | chat completions with image output |
| `comfyui` or `comfyui:<workflow.json>` | local ComfyUI |
| `mcp:<server>` | a tool on any MCP server |
| `http:<api>` | a generic JSON HTTP API |

**ComfyUI.** Export your workflow with *Save (API Format)* and put placeholders in it: `{{PROMPT}}`, `{{NEGATIVE_PROMPT}}`, `{{WIDTH}}`, `{{HEIGHT}}`, `{{SEED}}`, `{{STEPS}}`, `{{CFG}}`, `{{SAMPLER}}`, `{{SCHEDULER}}`, `{{CHECKPOINT}}`, `{{ASPECT_RATIO}}`. A placeholder that is the whole value keeps its numeric type. The bundled SDXL workflow is `config/comfyui_workflows/sdxl_txt2img_api.json`. Long figure descriptions are condensed into a short diffusion prompt by the *fast* model (can be disabled).

**MCP.** Configure servers under `image.mcp_servers` (Settings → Image):

```json
"my-image-server": {
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "your-image-mcp-server"],
  "env": {"API_KEY": "${MY_IMAGE_KEY}"},
  "tool": "generate_image",
  "prompt_arg": "prompt",
  "extra_args": {"width": "{{WIDTH}}", "height": "{{HEIGHT}}"},
  "timeout": 600
}
```

`transport` can also be `sse` or `streamable_http` (with `url` and `headers`). Image results, embedded resources, data URLs, http(s) URLs, local file paths and base64 text are all accepted. **List tools** in Settings shows what a server offers.

**HTTP API.** Configure under `image.http_apis`:

```json
"my-api": {
  "url": "https://example.com/v1/generate",
  "method": "POST",
  "headers": {"Authorization": "Bearer ${MY_KEY}"},
  "body": {"prompt": "{{PROMPT}}", "width": "{{WIDTH}}", "height": "{{HEIGHT}}"},
  "response_path": "data.0.b64_json",
  "timeout": 600
}
```

The response may be raw image bytes, or JSON whose `response_path` value is base64, a data URL or an image URL. For asynchronous APIs add `"poll": {"url_path": "urls.get", "status_path": "status", "done_values": ["succeeded"], "interval": 2}`.

## Pipeline, projects and the command line

### Stages

`outline → literature + figures (in parallel) → sections → refinement`

Each stage reads its inputs from disk, so a run can start from any stage, for example from **literature** after editing the outline, or from **sections** after replacing figures. Progress is written to `<project>/status.json`. Without LaTeX the refinement stage is skipped and the section-writing draft is finalized.

### Project folder

```
projects/<name>/
  project.json                   per-project settings
  raw_materials/                 idea.md, experimental_log.md, figures/ (+ info.json captions)
  outline_plan.json              outline from the outline agent (editable)
  outline.json                   outline with citations (after literature)
  literature_agent_output/       citation_map.json, references.bib
  plotting_results.json          generated figures: captions, engines, critic history
  figures/  figures/src/         generated images and their source code
  latex_writeup/                 working LaTeX, raw_draft_paper.tex
  content_refinement_workdir/    review/refine iterations
  final/final_paper.tex          self-contained, compilable final paper
  final_paper.pdf
  revisions/rev_NNN/             before/after for every manual revision
  exports/  logs/  status.json  ai_review.json  time_breakdown.json
```

### `paper_writing_cli.py`

```bash
python paper_writing_cli.py \
  --raw_materials_dir path/to/raw_materials \
  --latex_template_dir templates/cvpr2025 \
  --output_dir projects/my_paper \
  --use_plotting true \
  --writer_model_name ollama:qwen3:32b \
  --image_model_name comfyui
```

| Argument | Meaning |
|---|---|
| `--raw_materials_dir` | idea + experimental log folder (optional when resuming an existing `--output_dir`) |
| `--latex_template_dir` | template folder, e.g. `templates/cvpr2025` (remembered when resuming) |
| `--output_dir` | project / output folder (timestamped folder if omitted) |
| `--idea_filename`, `--experimental_log_filename` | file names inside raw materials (defaults `idea_sparse.md`, `experimental_log.md`) |
| `--writer_model_name`, `--reflection_model_name`, `--plotting_model_name`, `--search_model_name` | models per role (`provider:model`) |
| `--image_model_name` | diagram image backend |
| `--use_plotting` | generate figures (default `false`) |
| `--plot_engine`, `--diagram_engine` | figure engines |
| `--search_backend` | `auto`, `gemini`, `semantic_scholar`, `llm` |
| `--research_cutoff` | latest publication month to cite, `YYYY-MM` |
| `--plotting_max_critic_rounds`, `--max_reflections` | figure critique and content refinement rounds |
| `--start_stage`, `--end_stage` | `outline`, `literature`, `figures`, `sections`, `refinement` |
| `--list_providers` | print configured providers and default models |

Unset options fall back to `config/settings.json`. The original `paper_writing_cli.sh` (conda, Linux) still works.

### `po_tasks.py` (project tasks, also used by the UI)

```bash
python po_tasks.py run          --project projects/my_paper --start_stage sections
python po_tasks.py revise       --project projects/my_paper --instruction "Shorten the abstract" --section Abstract
python po_tasks.py regen-figure --project projects/my_paper --figure_id fig_1 --engine seaborn --instruction "Use horizontal bars"
python po_tasks.py render-code  --project projects/my_paper --figure_id fig_1
python po_tasks.py compile      --project projects/my_paper
python po_tasks.py export       --project projects/my_paper --formats pdf,docx,md,latex
python po_tasks.py review       --project projects/my_paper
```

## Export

PDF comes from LaTeX. Word and Markdown are converted with pandoc (bundled via `pypandoc_binary`): citations are rendered from the bibliography, PDF figures are rasterized, and Markdown images go to a `paper_media/` folder next to the file. You can upload a reference `.docx` in **Export** to apply your Word styles. If pandoc is missing, a simpler built-in converter is used.

## Tests

The suite runs offline: `tests/mock_backend.py` stands in for every LLM provider, ComfyUI and the HTTP image API, `tests/mcp_image_server.py` is a real MCP stdio server, and Semantic Scholar is stubbed. No API keys are read or sent.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest                  # everything (about 1 minute)
python -m pytest -m "not slow"    # skip the end-to-end pipeline and Remotion render
```

Renderer tests skip themselves when an optional tool is missing. With LaTeX installed, the end-to-end test also covers the refine loop and PDF compilation.

## Troubleshooting

| Symptom | Fix |
|---|---|
| No PDF; refinement shows *skipped* | install MiKTeX or TeX Live and re-run from the **refinement** stage |
| MiKTeX pop-ups asking to install packages | `initexmf --set-config-value=[MPM]AutoInstall=1` (install.bat does this) |
| Local model output is cut off or not valid JSON | raise Ollama `num_ctx` / llama.cpp `-c`; use a larger instruction-tuned model |
| Requests to a local server time out | raise the provider `timeout`, keep `max_concurrency` at 1 |
| Few or no references | add `SEMANTIC_SCHOLAR_API_KEY`; check the cutoff date |
| plotly engine marked *not installed* or fails | install Google Chrome, or run `python -c "import kaleido; kaleido.get_chrome_sync()"` |
| Remotion marked *not installed* | install Node.js 18+, then `npm install` in `tools/remotion` (or re-run install.bat) |
| Garbled text / `UnicodeDecodeError` on Windows | start through `start.bat`, or set `PYTHONUTF8=1` |

## Project structure

| Path | Contents |
|---|---|
| `methods/` | agents (`agents/`), prompts, and the staged pipeline (`pipeline.py`) |
| `utils/` | LLM providers, image backends, code renderers, export, settings, projects, PDF and Semantic Scholar helpers |
| `ui/` | PaperOrchestra Studio (Streamlit) |
| `config/` | default settings and ComfyUI workflows |
| `tools/remotion/` | Remotion workspace used to render code-defined figures |
| `templates/` | LaTeX templates; add your own folder with `template.tex` and `guidelines.md` |
| `autoraters/` | automated evaluation scripts |
| `tests/` | offline test suite |
| `frontend/` | the original Streamlit demo (kept for reference) |
| `paper_writing_cli.py`, `po_tasks.py` | command-line entry points |
| `install.bat`, `start.bat` | Windows installer and launcher |

## Dataset

The dataset used for paper generation is **not included** in this code repository. It will be released separately at a later date. Once available, download it and place it under the `datasets/` directory.

## Citation

If you find this repo or our paper helpful, please cite it as follows:

```bibtex
@article{song2026paperorchestra,
  title={PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing},
  author={Song, Yiwen and Song, Yale and Pfister, Tomas and Yoon, Jinsung},
  journal={arXiv preprint arXiv:2604.05018},
  year={2026}
}
```

# Disclaimer

This is not an officially supported Google product.
