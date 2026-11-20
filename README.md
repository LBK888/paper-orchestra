# <div align="center">🎻 PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing</div>
<div align="center">Yiwen Song<sup>1</sup>, Yale Song<sup>1</sup>, Tomas Pfister<sup>1</sup>, and Jinsung Yoon<sup>1</sup></div>
<div align="center"><sup>1</sup>Google Cloud AI Research</div>
<br><br>

PaperOrchestra is a multi-agent framework for automated AI research paper writing. It flexibly transforms unconstrained pre-writing materials (ideas and experimental logs) into submission-ready LaTeX manuscripts, including comprehensive literature synthesis and generated visuals, such as plots and conceptual diagrams.

Acting like an orchestrated team of specialized agents, it handles outline generation, literature review, section writing, content refinement, and plotting to close the gap between raw research materials and submission ready papers.

<div align="center">
  <img src="assets/overview.png" alt="PaperOrchestra Overview" width="90%"/>
</div>

## Key Features

- **Multi-Agent Pipeline**: Orchestrates specialized agents (Outline, Literature Review, Section Writing, Content Refinement, Plotting) for end-to-end paper generation.
- **Comprehensive Literature Synthesis**: Automatically searches, prioritizes, and integrates relevant literature into the manuscript.
- **Visuals Generation**: Generates plots and supports the inclusion of conceptual diagrams.
- **LaTeX Automation**: Produces submission-ready LaTeX manuscripts adhering to target conference templates.

## Windows quick start（Windows 快速開始）

```bat
install.bat      :: checks Python/LaTeX/Node, creates .venv, installs everything (install.bat /y = accept all optional tools)
start.bat        :: opens PaperOrchestra Studio at http://localhost:8501  (start.bat 8600 = other port)
```

`install.bat` 會檢查 Python（優先 3.12）、建立 `.venv` 並安裝 `requirements.txt`，並可選擇以 winget 安裝 MiKTeX（PDF 編譯）、Node.js 與 Remotion 工作區、Graphviz。
`start.bat` 啟動 Streamlit 介面 **PaperOrchestra Studio**：

| Page | What it does |
|---|---|
| 專案 Projects | create / open / import / export (.zip) / archive projects (`projects/<name>/`) |
| 輸入 Inputs | idea + experimental log editors, provided figures with captions, per-project models, engines, template |
| 執行 Run & status | run the full pipeline or a stage range, stop, live stage timeline and log tail |
| 結果 Results | PDF pages, outline, references, figures (+ critic history, source code), reviewer scores, AI review, timing |
| 修正 Revise | instruction-driven AI revision of the whole paper or one section (diff + history + revert), direct LaTeX editing + compile, outline editing + re-run, per-figure caption / replace / exclude / regenerate / edit-code-and-re-render |
| 匯出 Export | PDF, Word (.docx), Markdown (+ media), LaTeX source zip, whole-project zip |
| 設定 Settings | API keys (.env), LLM providers + model listing/ping, default models, image backends (ComfyUI / MCP / HTTP test), plotting engines, system check |

## LLM providers

Model names take a provider prefix; unprefixed names keep the original behaviour (`gpt*`/`o1`/`o3` → OpenAI, otherwise Gemini).

| Prefix | Backend | Default endpoint |
|---|---|---|
| `gemini:` | Gemini API key or Vertex AI | — |
| `openai:` | OpenAI | `https://api.openai.com/v1` |
| `openrouter:` | OpenRouter | `https://openrouter.ai/api/v1` |
| `ollama:` | Ollama native API (sets `num_ctx`) | `http://localhost:11434` |
| `llamacpp:` | llama.cpp `llama-server` | `http://localhost:8080/v1` |
| `vllm:` | vLLM OpenAI server | `http://localhost:8000/v1` |
| `lmstudio:` | LM Studio | `http://localhost:1234/v1` |
| `custom:` | any OpenAI-compatible endpoint | set in Settings |

Examples: `ollama:qwen3:32b`, `openrouter:anthropic/claude-sonnet-4.5`, `vllm:Qwen/Qwen3-32B`. Endpoints, timeouts, vision support and per-provider concurrency live in `config/settings.json` (edited from the UI; defaults in `config/settings.default.json`). `<think>` blocks from reasoning models are stripped automatically; images are dropped with a note for providers marked as non-vision.

Literature discovery (`--search_backend`): `gemini` (Google Search grounding, original), `semantic_scholar` (S2 keyword search + LLM re-ranking, works with any model), `llm` (model recall verified on S2). `auto` picks `gemini` for Gemini search models, else `semantic_scholar`.

## Figures: image backends and code-based plotting

Diagram images (`--image_model_name`): `gemini:<model>`, `openai:gpt-image-1` (Images API), `openrouter:<image model>`, `comfyui[:workflow.json]` (local ComfyUI, API-format workflow with `{{PROMPT}}`, `{{WIDTH}}`, … placeholders; default SDXL workflow in `config/comfyui_workflows/`), `mcp:<server>` (any MCP server tool returning an image; stdio, SSE or streamable HTTP), `http:<api>` (generic JSON API with templated body and `response_path`).

Plot / diagram engines (`--plot_engine`, `--diagram_engine`): `matplotlib`, `seaborn`, `plotly` (static export via kaleido), `graphviz` (DOT), `remotion` (React/TSX composition; the last frame becomes the paper figure, optional MP4 animation), and `image` for diagrams. LLM-written code runs in a separate process with a timeout and gets up to two automatic fix attempts; the source is kept in `<project>/figures/src/` so it can be edited and re-rendered from the UI or with `po_tasks.py render-code`.

## Stages and task runner

The pipeline is staged and resumable: `outline → literature (+ figures in parallel) → sections → refinement`. Progress is written to `<project>/status.json`.

```bash
python paper_writing_cli.py --output_dir projects/my_paper --latex_template_dir templates/cvpr2025 \
  --start_stage sections --writer_model_name ollama:qwen3:32b
python po_tasks.py revise       --project projects/my_paper --instruction "Shorten the abstract" --section Abstract
python po_tasks.py regen-figure --project projects/my_paper --figure_id fig_1 --engine seaborn --instruction "horizontal bars"
python po_tasks.py export       --project projects/my_paper --formats pdf,docx,md,latex
```

Without LaTeX installed the pipeline still produces `final/final_paper.tex` (and DOCX/Markdown exports) but skips the review-and-refine loop and PDF compilation.

## Tests

The suite runs offline: `tests/mock_backend.py` stands in for every LLM provider, ComfyUI and the HTTP image API, `tests/mcp_image_server.py` is a real MCP stdio server, and Semantic Scholar is stubbed. No API keys are read or sent.

```bash
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest                 # everything (~1 min)
.venv\Scripts\python -m pytest -m "not slow"   # skip the end-to-end pipeline and Remotion render (~15 s)
```

Renderer tests skip themselves when an optional tool is missing (Graphviz, Remotion, Chrome for plotly). With LaTeX installed, the end-to-end test also exercises the refine loop and PDF compilation.

## Installation

1.  **Environment Setup**: The project relies on a Conda environment named `paper_orchestra`. You can set up a similar environment with Python 3.11 and install the required dependencies.
    ```bash
    conda create -n paper_orchestra python=3.11
    conda activate paper_orchestra
    pip install -r requirements.txt
    ```

2.  **Environment Variables**: Create a `.env` file in the root of the project and add your API keys:
    ```env
    # Add keys if you have them, otherwise leave them empty
    # You need to specify related keys if you want to use the model
    # For example, if you want to use Gemini models, you need to specify either VERTEX_AI_PROJECT and VERTEX_AI_LOCATION, or GEMINI_API_KEY
    # If you want to use OpenAI models, you need to specify OPENAI_API_KEY
    
    SEMANTIC_SCHOLAR_API_KEY=your_semantic_scholar_api_key
    OPENAI_API_KEY=your_openai_api_key
    VERTEX_AI_PROJECT=your_vertex_ai_project
    VERTEX_AI_LOCATION=your_vertex_ai_location
    GEMINI_API_KEY=your_gemini_api_key

    # if you want to run demo and send emails to yourself at the end, set these 2 fields as well
    SMTP_EMAIL=your_email
    SMTP_PASSWORD=your_password
    ```

## Dataset

The dataset used for paper generation is **not included** in this code repository. It will be released separately at a later date.
Once available, you should download the dataset and place it under the `datasets/` directory.

## Usage

You can run the paper generation pipeline using the provided bash script or directly via the Python CLI.

### Using the Bash Script
```bash
./paper_writing_cli.sh
```

### Using the Python CLI directly
```bash
python paper_writing_cli.py \
  --raw_materials_dir /path_to_your_raw_materials/ \
  --latex_template_dir /path_to_your_latex_template/ \
  --output_dir /path_to_your_output_folder/ \
  --use_plotting true
```

### Key Arguments
*   `--raw_materials_dir`: (Required) Directory containing the raw materials (e.g., idea and experimental log).
*   `--latex_template_dir`: (Required) Directory containing the LaTeX template (e.g., `templates/cvpr2025`).
*   `--output_dir`: Directory to output the generated paper. If not specified, an automatic folder with a timestamp is created.
*   `--use_plotting`: Enable the plotting agent workflow to generate figures from code (Default: `False`).
*   `--writer_model_name`: LLM for writer and literature agents.
*   `--reflection_model_name`: LLM for reflection agents.

### Interactive Demo

We provide an interactive Streamlit demo for the paper generation pipeline. For instructions on how to run and use it, please refer to the [README.md](frontend/README.md) in the `frontend` directory.

## Project Structure

*   `autoraters/`: Contains scripts for automated evaluation.
*   `methods/`: Core logic for agents and pipeline execution.
*   `templates/`: LaTeX templates for target conferences, you can add your own template by creating a new subfolder under this directory.
*   `utils/`: Utility functions for API calls, PDF handling, etc.

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
