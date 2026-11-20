# <div align="center">🎻 PaperOrchestra：自動撰寫 AI 研究論文的多代理人框架</div>
<div align="center">Yiwen Song<sup>1</sup>, Yale Song<sup>1</sup>, Tomas Pfister<sup>1</sup>, and Jinsung Yoon<sup>1</sup></div>
<div align="center"><sup>1</sup>Google Cloud AI Research</div>
<br>
<div align="center"><a href="README.md">English</a> | <b>繁體中文（台灣）</b></div>
<br>

PaperOrchestra 是一套自動撰寫 AI 研究論文的多代理人（multi-agent）框架。它能把沒有固定格式的寫作前素材（研究想法與實驗紀錄）轉換成可直接投稿的 LaTeX 論文，內容包含完整的文獻整理，以及自動產生的視覺內容，例如數據圖與概念示意圖。

整個系統就像一支分工明確的團隊：由各司其職的代理人負責產生大綱、文獻回顧、章節撰寫、內容修訂與作圖，補上「原始研究素材」到「可投稿論文」之間的落差。

<div align="center">
  <img src="assets/overview.png" alt="PaperOrchestra 架構總覽" width="90%"/>
</div>

> **關於此分支（fork）。** [LBK888/paper-orchestra](https://github.com/LBK888/paper-orchestra) 在 Google Research 原始版本之上新增：支援任何 LLM 供應商（本機或雲端）、可替換的圖片生成方式（ComfyUI、MCP、HTTP API）、以程式繪製的科學圖表（matplotlib、seaborn、plotly、Graphviz、Remotion）、具人工介入修正功能的網頁介面、DOCX／Markdown 匯出、可從任一階段接續執行的流程、Windows 安裝程式，以及可離線執行的測試。

## 目錄

- [主要功能](#主要功能)
- [快速開始](#快速開始)
- [用介面寫出第一篇論文](#用介面寫出第一篇論文)
- [設定](#設定)
- [圖表](#圖表)
- [流程、專案與命令列](#流程專案與命令列)
- [匯出](#匯出)
- [測試](#測試)
- [疑難排解](#疑難排解)
- [專案結構](#專案結構)
- [引用](#引用)

## 主要功能

- **多代理人流程**：由專責代理人（大綱、文獻回顧、章節撰寫、內容修訂、作圖）把原始素材一路完成為論文。
- **完整的文獻整理**：自動搜尋、排序並引用相關研究，可設定文獻發表日期上限。
- **LaTeX 自動化**：直接套用研討會範本（`templates/cvpr2025`、`templates/iclr2025`，或你自己的範本）。
- **任何 LLM 皆可用**：Gemini、OpenAI、OpenRouter、Ollama、llama.cpp、vLLM、LM Studio，或任何相容 OpenAI 的端點；可依角色（撰寫、審稿、作圖、搜尋、修正）分別指定。
- **可替換的示意圖生成方式**：Gemini、OpenAI Images、OpenRouter、本機 ComfyUI、任何 MCP 伺服器工具，或通用 HTTP API。
- **以程式繪製的科學圖表**：matplotlib、seaborn、plotly、Graphviz 與 Remotion（以 React 製作的動畫圖，最後一格作為論文圖片，可另外輸出 MP4）。
- **PaperOrchestra Studio 網頁介面**：專案管理、即時執行狀態、檢視結果、人工與 AI 輔助修正、設定與匯出。
- **人工介入修正**：用文字指示修改單一章節，附差異比對、修訂紀錄與還原；可直接編輯 LaTeX 或大綱；任一張圖都能重新生成、替換或修改程式碼後重繪。
- **匯出**：PDF、Word（.docx）、Markdown，以及 LaTeX 原始碼壓縮檔。
- **可接續執行的流程**：修改素材、大綱或圖片後，可從任一階段重新開始。
- **支援 Windows**：`install.bat` 檢查電腦環境並安裝所有需要的套件；`start.bat` 開啟介面。

## 快速開始

### 系統需求

| 元件 | 用途 | 說明 |
|---|---|---|
| Python 3.10–3.13 | 全部功能 | 建議使用 3.12 |
| 一個 LLM | 全部功能 | 雲端 API 金鑰，或本機伺服器（Ollama、llama.cpp、vLLM、LM Studio） |
| LaTeX（MiKTeX 或 TeX Live） | 輸出 PDF 與「審稿—修訂」循環 | 沒有安裝時仍會產生 LaTeX、DOCX 與 Markdown |
| Node.js 18 以上 | Remotion 圖表 | 選用 |
| Graphviz | Graphviz 示意圖 | 選用 |
| Google Chrome | plotly 靜態圖片 | 選用；kaleido 也可自行下載 |
| Semantic Scholar API 金鑰 | 文獻搜尋 | 選用，但強烈建議（避免流量限制） |

### Windows

```bat
install.bat
start.bat
```

`install.bat` 會尋找合適的 Python、建立 `.venv` 虛擬環境、安裝 `requirements.txt`、由 `.env.example` 建立 `.env`，並詢問是否透過 winget 安裝 MiKTeX、Node.js 與 Remotion 工作區，以及 Graphviz。參數：`install.bat /y` 全部選用元件都安裝；`install.bat /minimal` 只安裝 Python 套件。

`start.bat` 會在 http://localhost:8501 開啟 **PaperOrchestra Studio**（`start.bat 8600` 可改用其他連接埠）。

### macOS／Linux（手動安裝）

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                   # 填入你的金鑰
(cd tools/remotion && npm install)                     # 選用：Remotion 圖表
PYTHONUTF8=1 streamlit run ui/app.py
```

## 用介面寫出第一篇論文

1. **設定 → 金鑰**：填入要使用的 API 金鑰（儲存在 `.env`）。若使用本機模型，請到 **設定 → LLM 供應商** 確認端點，並按 **列出模型**／**測試**。
2. **專案**：建立新專案（勾選「載入 CVPR 範例素材」即可取得現成範例）。
3. **輸入 → 素材**：撰寫或上傳研究想法與實驗紀錄；也可以上傳已完成的圖片並附上圖說。
4. **輸入 → 選項**：選擇範本、各角色使用的模型、圖表引擎、示意圖的圖片生成方式與文獻截止日期，然後按 **儲存選項**。
5. **執行與狀態**：按 **完整執行**，即可即時看到每個階段的進度與日誌。
6. **結果**：檢視論文、大綱、參考文獻、圖表（含自我審查紀錄與原始碼）與審稿分數；也可以執行 **AI 審稿**。
7. **修正**：要求修改特定章節、直接編輯 LaTeX 或大綱、個別修正圖表，之後重新編譯或從後面的階段重新執行。
8. **匯出**：下載 PDF、DOCX、Markdown、LaTeX 原始碼，或將整個專案打包成 zip。

| 頁面 | 功能 |
|---|---|
| 專案 | 建立、開啟、匯入／匯出（.zip）、封存（移到 `projects/.trash`） |
| 輸入 | 研究想法與實驗紀錄編輯器、自備圖片與圖說、各專案的模型、引擎、範本與截止日期 |
| 執行與狀態 | 完整執行或指定階段範圍、停止、即時階段進度與日誌 |
| 結果 | PDF 頁面、大綱、參考文獻、圖表、修訂分數、AI 審稿、耗時 |
| 修正 | 以 AI 修改整篇或單一章節（差異比對、修訂紀錄、還原）；直接編輯 LaTeX 並編譯；編輯大綱並重新執行；逐張圖修改圖說／替換／排除／重新生成／修改程式碼後重繪 |
| 匯出 | PDF、Word、Markdown（含圖片資料夾）、LaTeX 壓縮檔、專案壓縮檔 |
| 設定 | 金鑰、LLM 供應商、預設模型、圖片生成方式（含連線測試）、作圖引擎、文獻與流程選項、系統檢查 |

## 設定

### 設定檔

| 檔案 | 用途 |
|---|---|
| `.env` | API 金鑰（不納入 git），格式見 `.env.example`；可在 **設定 → 金鑰** 編輯 |
| `config/settings.default.json` | 隨程式提供的預設值，請勿修改 |
| `config/settings.json` | 你的自訂設定（不納入 git），由設定頁面寫入，會覆蓋預設值 |
| `projects/<名稱>/project.json` | 各專案的選擇（模型、範本、引擎等） |

設定環境變數 `PAPER_ORCHESTRA_SETTINGS=/path/to/settings.json` 可改用其他設定檔。

`.env` 會讀取的金鑰：`GEMINI_API_KEY`（或 `VERTEX_AI_PROJECT` + `VERTEX_AI_LOCATION`）、`OPENAI_API_KEY`、`OPENROUTER_API_KEY`、`VLLM_API_KEY`、`CUSTOM_LLM_API_KEY`、`SEMANTIC_SCHOLAR_API_KEY`、`PAPERBANANA_DIR`（選用，作圖的少量範例參考）、`SMTP_EMAIL`／`SMTP_PASSWORD`（僅舊版展示程式使用）。設定值中可用 `${變數名稱}` 引用環境變數。

### LLM 供應商

模型名稱前面加上供應商前綴。沒有前綴的名稱維持原本的行為（`gpt*`、`o1`、`o3`、`o4` → OpenAI，其餘 → Gemini）。

| 前綴 | 後端 | 預設端點 |
|---|---|---|
| `gemini:` | Gemini API 金鑰或 Vertex AI | — |
| `openai:` | OpenAI | `https://api.openai.com/v1` |
| `openrouter:` | OpenRouter | `https://openrouter.ai/api/v1` |
| `ollama:` | Ollama 原生 API | `http://localhost:11434` |
| `llamacpp:` | llama.cpp `llama-server` | `http://localhost:8080/v1` |
| `vllm:` | vLLM（相容 OpenAI 的伺服器） | `http://localhost:8000/v1` |
| `lmstudio:` | LM Studio 伺服器 | `http://localhost:1234/v1` |
| `custom:` | 任何相容 OpenAI 的端點 | 在設定頁面指定 |

範例：`gemini:gemini-3.1-pro-preview`、`openai:gpt-5`、`openrouter:anthropic/claude-sonnet-4.5`、`ollama:qwen3:32b`、`llamacpp:local`、`vllm:Qwen/Qwen3-32B`。其他相容 OpenAI 的服務（DeepSeek、Groq、Together、SiliconFlow 等）可在 **設定 → LLM 供應商 → 新增 OpenAI 相容端點** 加入。

啟動本機伺服器：

```bash
ollama pull qwen3:32b                      # Ollama（伺服器在背景執行）
llama-server -m model.gguf --port 8080 -c 32768   # llama.cpp
vllm serve Qwen/Qwen3-32B --port 8000      # vLLM
# LM Studio：載入模型後啟動本機伺服器
```

各供應商可設定：`base_url`、`api_key_env`、`timeout`（逾時秒數）、`max_concurrency`（最大並行數；Ollama、llama.cpp 與 LM Studio 預設一次一個請求，vLLM 預設 8）、`supports_vision`（設為 false 時圖片會以文字說明取代）、Ollama 的 `num_ctx`（上下文長度，預設 32768）與 `think`，以及相容 OpenAI 伺服器的 `extra_body`（例如 vLLM 的 `{"chat_template_kwargs": {"enable_thinking": false}}`）。推理模型輸出的 `<think>…</think>` 區塊會自動移除。

模型角色（設定 → 預設模型，或在各專案中指定）：**writer 撰寫**（大綱、文獻整理、章節）、**reflection 審稿修訂**、**plotting 作圖**（規劃、程式碼、自我審查）、**search 文獻搜尋**、**fast 輕量任務**（例如精簡 ComfyUI 提示詞）、**revision 人工修正**。

> 這個流程會送出很長的提示詞（整篇論文加上實驗紀錄）。本機模型需要夠大的上下文長度（32k 以上），且要能確實遵循指示，才能產生正確的 JSON 與 LaTeX。

### 文獻搜尋

`--search_backend`／設定 → 文獻：

| 方式 | 運作方式 |
|---|---|
| `gemini` | Gemini 搭配 Google 搜尋（原始行為） |
| `semantic_scholar` | 以 Semantic Scholar 關鍵字搜尋，再由 LLM 挑選相關結果；任何模型都能用 |
| `llm` | 由模型憑自身知識列出論文標題，再逐一到 Semantic Scholar 驗證 |
| `auto`（預設） | 搜尋模型是 Gemini 時用 `gemini`，否則用 `semantic_scholar` |

所有候選文獻在被引用前，都會經過 Semantic Scholar 核對，並依研究截止日期過濾。

## 圖表

開啟自動作圖時，大綱代理人會規劃需要哪些圖，作圖代理人再逐張規劃、套用風格、繪製並自我審查。你在 **輸入** 頁上傳的圖片會與自動產生的圖合併；關閉自動作圖時，只會使用你提供的圖片。

### 繪圖引擎

| 引擎 | 用途 | 需求 |
|---|---|---|
| `matplotlib` | 數據圖（預設）與以程式繪製的示意圖 | — |
| `seaborn` | 統計圖表 | — |
| `plotly` | 數據圖 | 輸出靜態圖片需要 Chrome |
| `graphviz` | 方塊與箭頭式示意圖（DOT 語法） | Graphviz |
| `remotion` | React／TSX 動畫圖；最後一格輸出為 PNG，可另外輸出 MP4 | Node.js + `tools/remotion` |
| `image` | 用圖片生成服務產生示意圖（示意圖預設） | 下方任一種圖片生成方式 |

LLM 寫出的程式會在獨立的 Python／Node 程序中執行並設有逾時；失敗時最多自動修正兩次，原始碼會存放在 `<專案>/figures/src/`，方便你在 **修正 → 圖表** 修改後重新繪製。這些程式以你的使用者權限執行，請使用你信任的模型。

Remotion 元件必須 `export const Figure`，且只能從 `react` 與 `remotion` 匯入；可參考 `tools/remotion/src/SampleFigure.tsx`（在 `tools/remotion` 執行 `npm run studio` 即可預覽）。尺寸、影格率、長度與是否輸出 MP4，可在 **設定 → 作圖** 調整。

### 示意圖的圖片生成方式

| 指定方式 | 後端 |
|---|---|
| `gemini:gemini-3-pro-image-preview` | Gemini 原生圖片生成（預設） |
| `openai:gpt-image-1`／`custom:<模型>` | 相容 OpenAI 的 `/images/generations` |
| `openrouter:<圖片模型>` | 透過 chat completions 輸出圖片 |
| `comfyui` 或 `comfyui:<workflow.json>` | 本機 ComfyUI |
| `mcp:<伺服器名稱>` | 任何 MCP 伺服器上的工具 |
| `http:<API 名稱>` | 通用 JSON HTTP API |

**ComfyUI。** 在 ComfyUI 以 *Save (API Format)* 匯出工作流程，並在其中放入佔位符：`{{PROMPT}}`、`{{NEGATIVE_PROMPT}}`、`{{WIDTH}}`、`{{HEIGHT}}`、`{{SEED}}`、`{{STEPS}}`、`{{CFG}}`、`{{SAMPLER}}`、`{{SCHEDULER}}`、`{{CHECKPOINT}}`、`{{ASPECT_RATIO}}`。若整個欄位值就是一個佔位符，代入後會保留數值型別。內附的 SDXL 工作流程位於 `config/comfyui_workflows/sdxl_txt2img_api.json`。過長的圖片描述會先由 *fast* 模型精簡成適合擴散模型的短提示詞（可關閉）。

**MCP。** 在 `image.mcp_servers`（設定 → 圖片生成）中設定伺服器：

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

`transport` 也可以是 `sse` 或 `streamable_http`（搭配 `url` 與 `headers`）。可接受的回傳格式包括圖片內容、內嵌資源、data URL、http(s) 網址、本機檔案路徑與 base64 文字。在設定頁按 **列出工具** 可查看伺服器提供哪些工具。

**HTTP API。** 在 `image.http_apis` 中設定：

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

回應可以是圖片的原始位元組，或是 JSON；JSON 中 `response_path` 指到的值可以是 base64、data URL 或圖片網址。非同步的 API 可加上 `"poll": {"url_path": "urls.get", "status_path": "status", "done_values": ["succeeded"], "interval": 2}`。

## 流程、專案與命令列

### 執行階段

`outline 大綱 → literature 文獻 + figures 圖表（同時進行）→ sections 章節 → refinement 修訂`

每個階段都從磁碟讀取輸入，因此可以從任一階段開始執行，例如修改大綱後從 **literature** 開始，或替換圖片後從 **sections** 開始。進度會寫入 `<專案>/status.json`。沒有安裝 LaTeX 時會略過修訂階段，直接以章節撰寫的草稿作為最終版本。

### 專案資料夾

```
projects/<名稱>/
  project.json                   專案設定
  raw_materials/                 idea.md、experimental_log.md、figures/（+ info.json 圖說）
  outline_plan.json              大綱代理人產生的大綱（可編輯）
  outline.json                   加入引用後的大綱（文獻階段之後）
  literature_agent_output/       citation_map.json、references.bib
  plotting_results.json          自動產生的圖：圖說、引擎、自我審查紀錄
  figures/  figures/src/         產生的圖片與原始碼
  latex_writeup/                 工作中的 LaTeX、raw_draft_paper.tex
  content_refinement_workdir/    審稿與修訂的各輪結果
  final/final_paper.tex          可獨立編譯的最終論文
  final_paper.pdf
  revisions/rev_NNN/             每次人工修正前後的版本
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

| 參數 | 說明 |
|---|---|
| `--raw_materials_dir` | 研究想法與實驗紀錄所在的資料夾（接續既有的 `--output_dir` 時可省略） |
| `--latex_template_dir` | 範本資料夾，例如 `templates/cvpr2025`（接續執行時會沿用） |
| `--output_dir` | 專案／輸出資料夾（未指定時自動建立帶時間戳記的資料夾） |
| `--idea_filename`、`--experimental_log_filename` | 素材資料夾內的檔名（預設為 `idea_sparse.md`、`experimental_log.md`） |
| `--writer_model_name`、`--reflection_model_name`、`--plotting_model_name`、`--search_model_name` | 各角色使用的模型（`供應商:模型`） |
| `--image_model_name` | 示意圖的圖片生成方式 |
| `--use_plotting` | 是否自動產生圖表（預設 `false`） |
| `--plot_engine`、`--diagram_engine` | 圖表引擎 |
| `--search_backend` | `auto`、`gemini`、`semantic_scholar`、`llm` |
| `--research_cutoff` | 可引用文獻的最晚發表月份，格式 `YYYY-MM` |
| `--plotting_max_critic_rounds`、`--max_reflections` | 圖表自我審查與內容修訂的輪數 |
| `--start_stage`、`--end_stage` | `outline`、`literature`、`figures`、`sections`、`refinement` |
| `--list_providers` | 列出已設定的供應商與預設模型 |

未指定的參數會沿用 `config/settings.json`。原本的 `paper_writing_cli.sh`（conda、Linux）仍可使用。

### `po_tasks.py`（專案任務，介面也透過它執行）

```bash
python po_tasks.py run          --project projects/my_paper --start_stage sections
python po_tasks.py revise       --project projects/my_paper --instruction "把摘要縮短到 150 字" --section Abstract
python po_tasks.py regen-figure --project projects/my_paper --figure_id fig_1 --engine seaborn --instruction "改成水平長條圖"
python po_tasks.py render-code  --project projects/my_paper --figure_id fig_1
python po_tasks.py compile      --project projects/my_paper
python po_tasks.py export       --project projects/my_paper --formats pdf,docx,md,latex
python po_tasks.py review       --project projects/my_paper
```

## 匯出

PDF 由 LaTeX 編譯產生。Word 與 Markdown 透過 pandoc 轉換（由 `pypandoc_binary` 內附）：引用會依參考文獻檔產生，PDF 格式的圖會先轉成點陣圖，Markdown 的圖片則放在檔案旁的 `paper_media/` 資料夾。在 **匯出** 頁可以上傳參考用的 `.docx`，套用你自己的 Word 樣式。若沒有 pandoc，會改用較簡易的內建轉換器。

## 測試

測試完全離線執行：`tests/mock_backend.py` 模擬所有 LLM 供應商、ComfyUI 與 HTTP 圖片 API，`tests/mcp_image_server.py` 是真正的 MCP stdio 伺服器，Semantic Scholar 則以固定資料取代。測試不會讀取或送出任何 API 金鑰。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest                  # 全部測試（約 1 分鐘）
python -m pytest -m "not slow"    # 略過端對端流程與 Remotion 繪製
```

缺少選用工具時，相關的繪圖測試會自動略過。有安裝 LaTeX 時，端對端測試也會涵蓋修訂循環與 PDF 編譯。

## 疑難排解

| 狀況 | 解決方式 |
|---|---|
| 沒有產生 PDF，修訂階段顯示 *skipped* | 安裝 MiKTeX 或 TeX Live，再從 **refinement** 階段重新執行 |
| MiKTeX 一直跳出視窗要求安裝套件 | 執行 `initexmf --set-config-value=[MPM]AutoInstall=1`（install.bat 會自動設定） |
| 本機模型輸出被截斷或不是有效的 JSON | 調高 Ollama 的 `num_ctx`／llama.cpp 的 `-c`；改用較大的指令微調模型 |
| 對本機伺服器的請求逾時 | 調高該供應商的 `timeout`，`max_concurrency` 維持 1 |
| 參考文獻很少或沒有 | 設定 `SEMANTIC_SCHOLAR_API_KEY`；檢查截止日期 |
| plotly 引擎顯示「未安裝」或執行失敗 | 安裝 Google Chrome，或執行 `python -c "import kaleido; kaleido.get_chrome_sync()"` |
| Remotion 顯示「未安裝」 | 安裝 Node.js 18 以上，然後在 `tools/remotion` 執行 `npm install`（或重新執行 install.bat） |
| Windows 上出現亂碼或 `UnicodeDecodeError` | 透過 `start.bat` 啟動，或設定 `PYTHONUTF8=1` |

## 專案結構

| 路徑 | 內容 |
|---|---|
| `methods/` | 代理人（`agents/`）、提示詞，以及分階段的流程（`pipeline.py`） |
| `utils/` | LLM 供應商、圖片生成、程式繪圖、匯出、設定、專案、PDF 與 Semantic Scholar 等工具 |
| `ui/` | PaperOrchestra Studio（Streamlit） |
| `config/` | 預設設定與 ComfyUI 工作流程 |
| `tools/remotion/` | 用來繪製程式定義圖表的 Remotion 工作區 |
| `templates/` | LaTeX 範本；新增一個含 `template.tex` 與 `guidelines.md` 的資料夾即可加入自己的範本 |
| `autoraters/` | 自動評估程式 |
| `tests/` | 離線測試 |
| `frontend/` | 原本的 Streamlit 展示程式（保留作為參考） |
| `paper_writing_cli.py`、`po_tasks.py` | 命令列進入點 |
| `install.bat`、`start.bat` | Windows 安裝與啟動程式 |

## 資料集

論文生成所使用的資料集 **並未包含** 在此程式碼庫中，將於日後另行釋出。釋出後請下載並放在 `datasets/` 資料夾下。

## 引用

如果這個專案或論文對你有幫助，請引用：

```bibtex
@article{song2026paperorchestra,
  title={PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing},
  author={Song, Yiwen and Song, Yale and Pfister, Tomas and Yoon, Jinsung},
  journal={arXiv preprint arXiv:2604.05018},
  year={2026}
}
```

# 免責聲明

本專案並非 Google 官方支援的產品。
