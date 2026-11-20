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

import base64
import json
import os
import platform
import shutil
import sys
import tempfile

import streamlit as st

from ui_common import ROOT, image_backend_picker, model_picker
from utils.code_renderers import (
    DIAGRAM_ENGINES,
    PLOT_ENGINES,
    engine_available,
    remotion_status,
    render_python,
    render_remotion,
)
from utils.settings import load_settings, resolve_path, save_settings, set_env_var

KEY_VARS = [
    ("GEMINI_API_KEY", "Gemini API key"),
    ("VERTEX_AI_PROJECT", "Vertex AI project (optional, instead of GEMINI_API_KEY)"),
    ("VERTEX_AI_LOCATION", "Vertex AI location"),
    ("OPENAI_API_KEY", "OpenAI API key"),
    ("OPENROUTER_API_KEY", "OpenRouter API key"),
    ("VLLM_API_KEY", "vLLM API key (if the server uses --api-key)"),
    ("CUSTOM_LLM_API_KEY", "Custom endpoint API key"),
    ("SEMANTIC_SCHOLAR_API_KEY", "Semantic Scholar API key (recommended)"),
]


def _json_editor(label: str, value, key: str, height: int = 260):
    text = st.text_area(label, value=json.dumps(value, indent=2, ensure_ascii=False), height=height, key=key)
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return value, str(exc)


def _section_keys():
    st.caption("金鑰儲存在專案根目錄的 `.env`（不會被 git 追蹤）。留空表示不變更。 Keys are stored in `.env` (git-ignored). Blank = unchanged.")
    new_vals = {}
    for var, label in KEY_VARS:
        is_set = bool(os.environ.get(var))
        new_vals[var] = st.text_input(
            f"{label} `{var}`" + (" ✅" if is_set else ""),
            type="password",
            key=f"env_{var}",
            placeholder="(已設定 set)" if is_set else "",
        )
    if st.button("💾 儲存金鑰 Save keys"):
        n = 0
        for var, val in new_vals.items():
            if val.strip():
                set_env_var(var, val.strip())
                n += 1
        st.success(f"已更新 {n} 個金鑰。 Updated {n} key(s).")


def _section_providers(s: dict):
    providers = s["llm"]["providers"]
    st.caption(
        "模型名稱格式 `provider:model`。本機服務：Ollama `ollama serve`、llama.cpp `llama-server -m model.gguf --port 8080`、"
        "vLLM `vllm serve <model> --port 8000`、LM Studio 開啟 server。"
    )
    for name, cfg in providers.items():
        with st.expander(f"{name} — {cfg.get('label', cfg.get('type'))}"):
            ptype = cfg.get("type")
            if ptype != "gemini":
                cfg["base_url"] = st.text_input("Base URL", value=cfg.get("base_url", ""), key=f"p_{name}_url")
                c1, c2 = st.columns(2)
                cfg["api_key_env"] = c1.text_input("API key 環境變數 env var", value=cfg.get("api_key_env", "") or "", key=f"p_{name}_kenv") or None
                cfg["timeout"] = c2.number_input("Timeout (s)", 30, 36000, int(cfg.get("timeout") or 900), key=f"p_{name}_to")
                c3, c4 = st.columns(2)
                mc = c3.number_input("最大並行 Max concurrency (0 = unlimited)", 0, 64, int(cfg.get("max_concurrency") or 0), key=f"p_{name}_mc")
                cfg["max_concurrency"] = int(mc) or None
                cfg["supports_vision"] = c4.checkbox("支援影像 Vision (send images)", value=bool(cfg.get("supports_vision")), key=f"p_{name}_vis")
            if ptype == "ollama":
                c1, c2 = st.columns(2)
                cfg["num_ctx"] = c1.number_input("num_ctx (context window)", 2048, 1048576, int(cfg.get("num_ctx") or 32768), step=4096, key=f"p_{name}_ctx")
                think = c2.selectbox("think (reasoning models)", ["default", "on", "off"],
                                     index={None: 0, True: 1, False: 2}.get(cfg.get("think"), 0), key=f"p_{name}_think")
                cfg["think"] = {"default": None, "on": True, "off": False}[think]
            if ptype == "openai_compatible":
                extra, err = _json_editor("extra_body (JSON，例如 vLLM {\"chat_template_kwargs\": {\"enable_thinking\": false}})",
                                          cfg.get("extra_body") or {}, key=f"p_{name}_extra", height=100)
                if err:
                    st.error(err)
                else:
                    cfg["extra_body"] = extra
                if name not in ("openai", "openrouter"):
                    cfg["image_mode"] = st.selectbox("圖片生成 API Image mode", ["images_api", "chat_modalities"],
                                                     index=0 if cfg.get("image_mode", "images_api") == "images_api" else 1,
                                                     key=f"p_{name}_imode")
            c1, c2 = st.columns(2)
            if c1.button("📋 列出模型 List models", key=f"p_{name}_list"):
                try:
                    from utils.llm_providers import list_models

                    models = list_models(name)
                    st.session_state.setdefault("model_lists", {})[name] = models
                    st.success(f"{len(models)} models")
                    st.write(models[:200])
                except Exception as exc:
                    st.error(f"失敗 Failed: {exc}")
            with c2.popover("🧪 測試 Test a model"):
                mname = st.text_input("model", key=f"p_{name}_ping_model")
                if st.button("Ping", key=f"p_{name}_ping") and mname:
                    from utils.llm_providers import ping_model

                    ok, msg, secs = ping_model(f"{name}:{mname}")
                    (st.success if ok else st.error)(f"{'OK' if ok else 'FAIL'} ({secs:.1f}s): {msg}")

    with st.expander("➕ 新增 OpenAI 相容端點 Add an OpenAI-compatible provider"):
        new_name = st.text_input("名稱 Name (e.g. deepseek, together, groq, siliconflow)", key="newprov_name")
        new_url = st.text_input("Base URL (…/v1)", key="newprov_url")
        new_env = st.text_input("API key env var", key="newprov_env", value="")
        if st.button("新增 Add") and new_name and new_url:
            providers[new_name.strip().lower()] = {
                "type": "openai_compatible",
                "label": new_name,
                "base_url": new_url,
                "api_key_env": new_env or None,
                "supports_vision": False,
                "timeout": 1800,
                "max_concurrency": 4,
            }
            st.session_state["settings_dirty"] = True


def _section_models(s: dict):
    st.caption("新專案的預設模型（各專案可在「輸入 → 選項」覆寫）。 Defaults for new projects.")
    dm = s["llm"]["default_models"]
    for role, label in (
        ("writer", "撰寫 Writer"),
        ("reflection", "審稿修訂 Reflection"),
        ("plotting", "作圖 Plotting"),
        ("search", "文獻搜尋 Search"),
        ("fast", "輕量任務 Fast (prompt condensing, parsing)"),
        ("revision", "人工修正 Revision"),
    ):
        dm[role] = model_picker(label, dm.get(role), key=f"dm_{role}")
    providers = list(s["llm"]["providers"].keys())
    s["llm"]["default_provider"] = st.selectbox(
        "無前綴模型名稱的預設 provider Default provider for un-prefixed names", providers,
        index=providers.index(s["llm"].get("default_provider", "gemini")) if s["llm"].get("default_provider") in providers else 0,
    )


def _section_image(s: dict):
    img = s["image"]
    img["default_backend"] = image_backend_picker("預設示意圖生成 Default diagram backend", img.get("default_backend"), key="img_default")

    st.markdown("#### ComfyUI")
    cu = img["comfyui"]
    c1, c2 = st.columns(2)
    cu["base_url"] = c1.text_input("ComfyUI URL", value=cu.get("base_url", ""), key="cu_url")
    cu["checkpoint"] = c2.text_input("Checkpoint (ckpt_name)", value=cu.get("checkpoint", ""), key="cu_ckpt")
    cu["workflow_path"] = st.text_input(
        "Workflow (API format JSON；用 {{PROMPT}} {{NEGATIVE_PROMPT}} {{WIDTH}} {{HEIGHT}} {{SEED}} {{STEPS}} {{CFG}} {{SAMPLER}} {{SCHEDULER}} {{CHECKPOINT}} 佔位)",
        value=cu.get("workflow_path", ""), key="cu_wf",
    )
    wf_up = st.file_uploader("上傳 workflow（ComfyUI → Export (API)）Upload API-format workflow", type=["json"], key="cu_wf_up")
    if wf_up is not None and st.button("儲存 workflow Save workflow"):
        dst = os.path.join(ROOT, "config", "comfyui_workflows", wf_up.name)
        with open(dst, "wb") as f:
            f.write(wf_up.getbuffer())
        cu["workflow_path"] = os.path.relpath(dst, ROOT).replace("\\", "/")
        st.success(f"Saved to {cu['workflow_path']} (remember to Save settings)")
    c1, c2, c3, c4 = st.columns(4)
    cu["steps"] = c1.number_input("steps", 1, 200, int(cu.get("steps", 30)), key="cu_steps")
    cu["cfg"] = c2.number_input("cfg", 0.0, 30.0, float(cu.get("cfg", 6.5)), key="cu_cfg")
    cu["sampler"] = c3.text_input("sampler", value=cu.get("sampler", "euler"), key="cu_sampler")
    cu["scheduler"] = c4.text_input("scheduler", value=cu.get("scheduler", "normal"), key="cu_sched")
    cu["negative_prompt"] = st.text_input("negative prompt", value=cu.get("negative_prompt", ""), key="cu_neg")
    c1, c2, c3 = st.columns(3)
    cu["megapixels"] = c1.number_input("megapixels", 0.25, 4.0, float(cu.get("megapixels", 1.0)), step=0.25, key="cu_mp")
    cu["condense_prompt"] = c2.checkbox("用 LLM 精簡 prompt Condense prompt", value=bool(cu.get("condense_prompt", True)), key="cu_cond")
    cu["timeout"] = c3.number_input("timeout (s)", 30, 7200, int(cu.get("timeout", 900)), key="cu_to")
    if st.button("🔌 測試 ComfyUI 連線 Test connection"):
        from utils.image_backends import test_comfyui

        ok, msg = test_comfyui()
        (st.success if ok else st.error)(msg)

    st.markdown("#### MCP servers")
    st.caption(
        "transport: `stdio`（command/args/env）、`sse` 或 `streamable_http`（url/headers）。`tool` 為產圖工具名稱，"
        "`prompt_arg` 為 prompt 參數名，`extra_args` 可用 {{WIDTH}} {{HEIGHT}} {{ASPECT_RATIO}} {{SEED}}。"
    )
    servers, err = _json_editor("mcp_servers", img.get("mcp_servers", {}), key="mcp_json", height=300)
    if err:
        st.error(f"JSON error: {err}")
    else:
        img["mcp_servers"] = servers
    if servers:
        c1, c2 = st.columns([2, 1])
        srv = c1.selectbox("伺服器 Server", list(servers.keys()), key="mcp_test_srv")
        if c2.button("🔌 列出工具 List tools"):
            st.info("使用已儲存的設定。 Uses saved settings (Save first).")
            try:
                from utils.image_backends import list_mcp_tools

                st.json(list_mcp_tools(srv))
            except Exception as exc:
                st.error(f"失敗 Failed: {exc}")

    st.markdown("#### HTTP APIs")
    st.caption(
        "通用 JSON API：`url`、`method`、`headers`（可用 ${ENV_VAR}）、`body`（{{PROMPT}} 等佔位）、"
        "`response_path`（如 data.0.b64_json 或 images.0.url）；非同步任務可加 `poll`。"
    )
    apis, err = _json_editor("http_apis", img.get("http_apis", {}), key="http_json", height=260)
    if err:
        st.error(f"JSON error: {err}")
    else:
        img["http_apis"] = apis

    st.markdown("#### 🧪 測試產圖 Test image generation (uses saved settings)")
    c1, c2 = st.columns([2, 1])
    prompt = c1.text_input("Prompt", value="A clean flat vector diagram of an encoder-decoder neural network, white background", key="img_test_prompt")
    backend = image_backend_picker("Backend", img.get("default_backend"), key="img_test_backend")
    if st.button("產生 Generate test image"):
        from utils.image_backends import generate_image

        with st.spinner("Generating…"):
            b64 = generate_image(prompt, backend=backend, aspect_ratio="16:9", max_retries=1)
        if b64:
            st.image(base64.b64decode(b64))
        else:
            st.error("失敗，詳見終端機輸出。 Failed; see the console output.")


def _section_plotting(s: dict):
    pl = s["plotting"]
    c1, c2 = st.columns(2)
    pl["plot_engine"] = c1.selectbox(
        "預設數據圖引擎 Default plot engine", PLOT_ENGINES,
        index=PLOT_ENGINES.index(pl.get("plot_engine", "matplotlib")),
        format_func=lambda e: e + ("" if engine_available(e) else " (未安裝)"),
    )
    pl["diagram_engine"] = c2.selectbox(
        "預設示意圖引擎 Default diagram engine", DIAGRAM_ENGINES,
        index=DIAGRAM_ENGINES.index(pl.get("diagram_engine", "image")),
        format_func=lambda e: e + ("" if engine_available(e) else " (未安裝)"),
    )
    c1, c2 = st.columns(2)
    pl["code_timeout"] = c1.number_input("程式執行逾時 Code timeout (s)", 10, 3600, int(pl.get("code_timeout", 180)))
    pl["dpi"] = c2.number_input("DPI", 72, 1200, int(pl.get("dpi", 300)))
    st.markdown("#### Remotion")
    rs = remotion_status()
    st.write(
        f"Node: `{rs['node'] or '未找到 not found'}` · Remotion: "
        + ("✅ installed" if rs["installed"] else f"❌ not installed (run install.bat or `npm install` in {rs['project_dir']})")
    )
    rm = pl["remotion"]
    c1, c2, c3, c4 = st.columns(4)
    rm["width"] = c1.number_input("width", 320, 7680, int(rm.get("width", 1920)))
    rm["height"] = c2.number_input("height", 240, 4320, int(rm.get("height", 1080)))
    rm["fps"] = c3.number_input("fps", 1, 120, int(rm.get("fps", 30)))
    rm["duration_frames"] = c4.number_input("frames", 1, 3600, int(rm.get("duration_frames", 150)))
    rm["render_animation"] = st.checkbox("同時輸出 MP4 動畫 Also render an MP4 animation", value=bool(rm.get("render_animation")))

    st.markdown("#### 🧪 測試 Test renderers")
    c1, c2 = st.columns(2)
    if c1.button("matplotlib / seaborn"):
        code = (
            "import seaborn as sns, pandas as pd\n"
            "df = pd.DataFrame({'method':['A','B','C'],'acc':[71.2,75.9,80.3]})\n"
            "sns.set_theme(style='whitegrid', context='paper')\n"
            "ax = sns.barplot(data=df, x='method', y='acc', hue='method', palette='colorblind')\n"
            "ax.set_ylabel('Accuracy (%)')\n"
        )
        out = os.path.join(tempfile.mkdtemp(), "test.png")
        res = render_python(code, out)
        if res.ok:
            c1.image(out)
        else:
            c1.error(res.error)
    if c2.button("Remotion sample"):
        with open(os.path.join(rs["project_dir"], "src", "SampleFigure.tsx"), "r", encoding="utf-8") as f:
            code = f.read()
        out = os.path.join(tempfile.mkdtemp(), "remotion_test.png")
        with st.spinner("Rendering (first run bundles + starts Chrome, ~30-60s)…"):
            res = render_remotion(code, out, "ui_test_sample", render_animation=False)
        if res.ok:
            c2.image(out)
        else:
            c2.error(res.error[-2000:])


def _section_literature(s: dict):
    lit = s["literature"]
    opts = ["auto", "gemini", "semantic_scholar", "llm"]
    lit["search_backend"] = st.selectbox(
        "預設文獻搜尋 Default literature search", opts, index=opts.index(lit.get("search_backend", "auto")),
        help="auto：搜尋模型為 Gemini 時用 Google Search，否則用 Semantic Scholar。",
    )
    lit["s2_min_interval_sec"] = st.number_input("S2 最小請求間隔 Min interval (s)", 0.0, 10.0, float(lit.get("s2_min_interval_sec", 1.1)))
    lit["paperbanana_dir"] = st.text_input(
        "PaperBanana 目錄（few-shot 範例與風格指南，選用）PaperBanana checkout (optional)", value=lit.get("paperbanana_dir", "")
    )
    pipe = s["pipeline"]
    c1, c2, c3, c4 = st.columns(4)
    pipe["max_reflections"] = c1.number_input("refinement iterations", 0, 6, int(pipe.get("max_reflections", 3)))
    pipe["plotting_max_critic_rounds"] = c2.number_input("figure critic rounds", 0, 6, int(pipe.get("plotting_max_critic_rounds", 3)))
    pipe["max_pipeline_retries"] = c3.number_input("stage retries", 1, 5, int(pipe.get("max_pipeline_retries", 3)))
    pipe["latex_timeout"] = c4.number_input("LaTeX timeout (s)", 30, 1800, int(pipe.get("latex_timeout", 120)))
    s["ui"]["projects_dir"] = st.text_input("專案資料夾 Projects folder", value=s["ui"].get("projects_dir", "projects"))


def _section_system():
    from utils.export_utils import pandoc_path

    rows = [
        ("Python", sys.version.split()[0] + f" ({sys.executable})", True),
        ("OS", platform.platform(), True),
        ("pdflatex", shutil.which("pdflatex") or "未找到 not found → 安裝 MiKTeX: winget install MiKTeX.MiKTeX", bool(shutil.which("pdflatex"))),
        ("bibtex", shutil.which("bibtex") or "未找到 not found", bool(shutil.which("bibtex"))),
        ("pandoc", pandoc_path() or "未找到 not found (pip install pypandoc_binary)", bool(pandoc_path())),
        ("node", shutil.which("node") or "未找到 not found (Remotion 需要 Node.js 18+)", bool(shutil.which("node"))),
        ("Remotion", "installed" if remotion_status()["installed"] else "not installed", remotion_status()["installed"]),
        ("graphviz dot", shutil.which("dot") or "未找到 not found (選用 optional)", bool(shutil.which("dot"))),
    ]
    for eng in ("seaborn", "plotly"):
        rows.append((eng, "ok" if engine_available(eng) else "missing", engine_available(eng)))
    for name, value, ok in rows:
        st.markdown(f"{'✅' if ok else '⚠️'} **{name}** — `{value}`")


def render():
    st.header("⚙️ 設定 Settings")
    s = load_settings()
    tabs = st.tabs(["🔑 金鑰 Keys", "🤖 LLM 供應商 Providers", "🎯 預設模型 Models", "🎨 圖片生成 Image",
                    "📊 作圖 Plotting", "📚 文獻/管線 Literature & pipeline", "🩺 系統檢查 System"])
    with tabs[0]:
        _section_keys()
    with tabs[1]:
        _section_providers(s)
    with tabs[2]:
        _section_models(s)
    with tabs[3]:
        _section_image(s)
    with tabs[4]:
        _section_plotting(s)
    with tabs[5]:
        _section_literature(s)
    with tabs[6]:
        _section_system()

    st.divider()
    if st.button("💾 儲存設定 Save settings", type="primary", width="stretch") or st.session_state.pop("settings_dirty", False):
        s.pop("_comment", None)
        path = save_settings(s)
        st.success(f"已儲存至 Saved to `{os.path.relpath(path, ROOT)}`")
