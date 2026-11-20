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

"""Pluggable image-generation backends for diagrams.

Backend specs (``--image_model_name`` / Settings > Image):

* ``gemini:<model>`` or a bare legacy name -> Gemini native image generation
* ``openai:<model>`` / ``custom:<model>``   -> OpenAI-compatible ``/images/generations``
* ``openrouter:<model>``                     -> chat completions with ``modalities=[image,text]``
* ``comfyui`` or ``comfyui:<workflow.json>`` -> local ComfyUI (API-format workflow)
* ``mcp:<server-name>``                      -> any MCP server tool that returns an image
* ``http:<api-name>``                        -> generic JSON HTTP API with templated body

Every backend returns the image as a base64 string (or ``None`` on failure).
"""

import asyncio
import base64
import copy
import io
import json
import os
import random
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

from utils.settings import expand_env, get_setting, load_settings, resolve_path

PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def parse_aspect_ratio(aspect_ratio: str) -> float:
    try:
        w, h = str(aspect_ratio).split(":")
        return max(0.1, float(w) / float(h))
    except Exception:
        return 16 / 9


def aspect_to_size(aspect_ratio: str, megapixels: float = 1.0, multiple: int = 64) -> Tuple[int, int]:
    ratio = parse_aspect_ratio(aspect_ratio)
    area = megapixels * 1024 * 1024
    width = (area * ratio) ** 0.5
    height = width / ratio
    width = max(multiple, int(round(width / multiple)) * multiple)
    height = max(multiple, int(round(height / multiple)) * multiple)
    return width, height


def openai_size_for(model: str, aspect_ratio: str) -> str:
    ratio = parse_aspect_ratio(aspect_ratio)
    low = model.lower()
    if "dall-e-3" in low:
        return "1792x1024" if ratio > 1.2 else "1024x1792" if ratio < 0.83 else "1024x1024"
    if "dall-e-2" in low:
        return "1024x1024"
    if "gpt-image" in low or "chatgpt-image" in low:
        return "1536x1024" if ratio > 1.2 else "1024x1536" if ratio < 0.83 else "1024x1024"
    w, h = aspect_to_size(aspect_ratio)
    return f"{w}x{h}"


def fill_placeholders(template: Any, values: Dict[str, Any]) -> Any:
    """Replaces ``{{NAME}}`` placeholders; a value that is exactly one
    placeholder keeps the substituted value's type (int/float)."""
    if isinstance(template, str):
        whole = PLACEHOLDER.fullmatch(template.strip())
        if whole and whole.group(1) in values:
            return values[whole.group(1)]
        return PLACEHOLDER.sub(
            lambda m: str(values.get(m.group(1), m.group(0))), template
        )
    if isinstance(template, dict):
        return {k: fill_placeholders(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill_placeholders(v, values) for v in template]
    return template


def get_by_path(data: Any, path: str) -> Any:
    """Resolves ``a.b.0.c`` style paths."""
    node = data
    for key in [k for k in (path or "").split(".") if k != ""]:
        if isinstance(node, list):
            node = node[int(key)]
        elif isinstance(node, dict):
            node = node[key]
        else:
            raise KeyError(f"Cannot resolve '{key}' in {type(node).__name__}")
    return node


def _download(url: str, timeout: float = 120) -> bytes:
    rsp = requests.get(url, timeout=timeout)
    rsp.raise_for_status()
    return rsp.content


def bytes_from_reference(value: Any, timeout: float = 120) -> Optional[bytes]:
    """Turns a base64 string / data URL / http URL / local path / dict into bytes."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, dict):
        for key in ("b64_json", "b64", "base64", "image_base64", "data", "image", "url", "path", "file", "uri"):
            if key in value:
                got = bytes_from_reference(value[key], timeout)
                if got:
                    return got
        return None
    if isinstance(value, list):
        for item in value:
            got = bytes_from_reference(item, timeout)
            if got:
                return got
        return None
    text = str(value).strip()
    if text.startswith("data:"):
        return base64.b64decode(text.split(",", 1)[1])
    if text.startswith(("http://", "https://")):
        return _download(text, timeout)
    if text.startswith("file://"):
        text = text[7:]
        if re.match(r"^/[A-Za-z]:", text):
            text = text[1:]
    if len(text) < 1024 and os.path.isfile(text):
        with open(text, "rb") as f:
            return f.read()
    if text.startswith("{") or text.startswith("["):
        try:
            return bytes_from_reference(json.loads(text), timeout)
        except json.JSONDecodeError:
            pass
    url_match = re.search(r"https?://\S+\.(?:png|jpe?g|webp|gif)(?:\?\S*)?", text, re.I)
    if url_match:
        return _download(url_match.group(0), timeout)
    compact = re.sub(r"\s+", "", text)
    if len(compact) > 200 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact):
        try:
            return base64.b64decode(compact + "=" * (-len(compact) % 4))
        except Exception:
            return None
    return None


def to_png_bytes(data: bytes) -> bytes:
    """Re-encodes any raster image as PNG (keeps PNG untouched)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def _b64(data: Optional[bytes]) -> Optional[str]:
    return base64.b64encode(data).decode("utf-8") if data else None


def _save(data: Optional[bytes], save_path: Optional[str]):
    if data and save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "wb") as fh:
            fh.write(data)


# ---------------------------------------------------------------------------
# backend parsing
# ---------------------------------------------------------------------------


def parse_backend(spec: Optional[str]) -> Tuple[str, str]:
    """Returns (kind, target). kind in gemini|openai_images|openai_chat|comfyui|mcp|http."""
    spec = (spec or get_setting("image.default_backend", "gemini:gemini-3-pro-image-preview")).strip()
    prefix, _, rest = spec.partition(":")
    prefix_l = prefix.lower()
    if prefix_l == "comfyui":
        return "comfyui", rest
    if prefix_l == "mcp":
        return "mcp", rest
    if prefix_l == "http":
        return "http", rest
    providers = load_settings().get("llm", {}).get("providers", {})
    if rest and prefix_l in providers:
        cfg = providers[prefix_l]
        if cfg.get("type") == "gemini":
            return "gemini", rest
        if cfg.get("type") == "openai_compatible":
            mode = cfg.get("image_mode", "images_api")
            return ("openai_chat" if mode == "chat_modalities" else "openai_images"), spec
        raise ValueError(f"Provider '{prefix_l}' ({cfg.get('type')}) cannot generate images.")
    return "gemini", spec  # legacy bare model name


# ---------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------


def _gemini(model: str, prompt: str, aspect_ratio: str, system_instruction: Optional[str]) -> Optional[bytes]:
    from utils.gemini_utils import generate_image_with_gemini

    configs = {"system_instruction": system_instruction} if system_instruction else {}
    b64 = generate_image_with_gemini(
        model_name=model, prompt=prompt, aspect_ratio=aspect_ratio, generation_configs=configs
    )
    return base64.b64decode(b64) if b64 else None


def _openai_images(spec: str, prompt: str, aspect_ratio: str) -> Optional[bytes]:
    from utils.llm_providers import _get_openai_client, resolve_model

    resolved = resolve_model(spec)
    client = _get_openai_client(resolved.provider, resolved.cfg)
    kwargs: Dict[str, Any] = {
        "model": resolved.model,
        "prompt": prompt[:32000],
        "n": 1,
        "size": openai_size_for(resolved.model, aspect_ratio),
    }
    if "dall-e" in resolved.model.lower():
        kwargs["response_format"] = "b64_json"
        kwargs["prompt"] = prompt[:3900]
    rsp = client.images.generate(**kwargs)
    item = rsp.data[0]
    if getattr(item, "b64_json", None):
        return base64.b64decode(item.b64_json)
    if getattr(item, "url", None):
        return _download(item.url)
    return None


def _openai_chat_image(spec: str, prompt: str, aspect_ratio: str) -> Optional[bytes]:
    from utils.llm_providers import _get_openai_client, resolve_model

    resolved = resolve_model(spec)
    client = _get_openai_client(resolved.provider, resolved.cfg)
    rsp = client.chat.completions.create(
        model=resolved.model,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"modalities": ["image", "text"], "image_config": {"aspect_ratio": aspect_ratio}},
    )
    message = rsp.choices[0].message.model_dump()
    images = message.get("images") or []
    for img in images:
        url = (img.get("image_url") or {}).get("url") if isinstance(img, dict) else None
        data = bytes_from_reference(url)
        if data:
            return data
    content = message.get("content")
    if isinstance(content, list):
        return bytes_from_reference(content)
    return bytes_from_reference(content) if content else None


def condense_prompt_for_diffusion(prompt: str, max_words: int = 120) -> str:
    """Diffusion text encoders are short; ask the fast LLM for a compact prompt."""
    try:
        from utils.llm_backend_utils import call_llm_with_contents

        instruction = (
            "Rewrite the following figure description as a single prompt for a text-to-image diffusion "
            f"model. Keep it under {max_words} words, comma-separated visual phrases, mention layout, "
            "shapes, colors, clean white background, flat vector scientific illustration style. "
            "Keep only the most important short text labels in quotes. Output the prompt only.\n\n"
            f"Description:\n{prompt}"
        )
        rsp = call_llm_with_contents(
            contents=[instruction],
            model_name=get_setting("llm.default_models.fast", "gemini-3-flash-preview"),
            generation_configs={"temperature": 0.3},
            return_json=False,
            check_parsed_response_not_none=False,
            max_retries=2,
        )
        text = (rsp.get("raw_response") or "").strip().strip('"')
        return text or prompt
    except Exception as exc:
        print(f"[image] prompt condensation failed ({exc}); using the full prompt.")
        return prompt


def load_comfy_workflow(target: str) -> Tuple[dict, str]:
    cfg = get_setting("image.comfyui", {}) or {}
    candidates = []
    if target:
        candidates += [target, os.path.join("config", "comfyui_workflows", target)]
        if not target.endswith(".json"):
            candidates.append(os.path.join("config", "comfyui_workflows", target + ".json"))
    candidates.append(cfg.get("workflow_path", ""))
    for cand in candidates:
        path = resolve_path(cand) if cand else ""
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), path
    raise FileNotFoundError(f"ComfyUI workflow not found (tried {candidates})")


def _comfyui(target: str, prompt: str, aspect_ratio: str, negative_prompt: Optional[str], seed: Optional[int]) -> Optional[bytes]:
    cfg = get_setting("image.comfyui", {}) or {}
    base = expand_env(cfg.get("base_url", "http://127.0.0.1:8188")).rstrip("/")
    timeout = float(cfg.get("timeout", 900))
    workflow, wf_path = load_comfy_workflow(target)
    if cfg.get("condense_prompt", True):
        prompt = condense_prompt_for_diffusion(prompt, int(cfg.get("max_prompt_words", 120)))
    width, height = aspect_to_size(aspect_ratio, float(cfg.get("megapixels", 1.0)))
    values = {
        "PROMPT": prompt,
        "NEGATIVE_PROMPT": negative_prompt if negative_prompt is not None else cfg.get("negative_prompt", ""),
        "WIDTH": width,
        "HEIGHT": height,
        "ASPECT_RATIO": aspect_ratio,
        "SEED": seed if seed is not None else random.randint(0, 2**31 - 1),
        "STEPS": int(cfg.get("steps", 30)),
        "CFG": float(cfg.get("cfg", 6.5)),
        "SAMPLER": cfg.get("sampler", "euler"),
        "SCHEDULER": cfg.get("scheduler", "normal"),
        "CHECKPOINT": cfg.get("checkpoint", ""),
    }
    graph = fill_placeholders(copy.deepcopy(workflow), values)
    client_id = str(uuid.uuid4())
    rsp = requests.post(f"{base}/prompt", json={"prompt": graph, "client_id": client_id}, timeout=60)
    if rsp.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected workflow {os.path.basename(wf_path)}: {rsp.text[:800]}")
    prompt_id = rsp.json()["prompt_id"]
    print(f"[ComfyUI] queued prompt {prompt_id} ({width}x{height})")

    deadline = time.time() + timeout
    while time.time() < deadline:
        hist = requests.get(f"{base}/history/{prompt_id}", timeout=30).json()
        entry = hist.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI execution error: {json.dumps(status)[:800]}")
            for node_out in entry.get("outputs", {}).values():
                for img in node_out.get("images", []) or []:
                    view = requests.get(
                        f"{base}/view",
                        params={
                            "filename": img["filename"],
                            "subfolder": img.get("subfolder", ""),
                            "type": img.get("type", "output"),
                        },
                        timeout=120,
                    )
                    view.raise_for_status()
                    return view.content
            if status.get("completed"):
                raise RuntimeError("ComfyUI finished without any image output node.")
        time.sleep(1.5)
    raise TimeoutError(f"ComfyUI did not finish within {timeout}s")


# --- MCP -------------------------------------------------------------------


def _mcp_server_cfg(name: str) -> dict:
    servers = get_setting("image.mcp_servers", {}) or {}
    if name not in servers:
        raise ValueError(f"MCP server '{name}' is not configured (Settings > Image > MCP).")
    return expand_env(servers[name])


async def _with_mcp_session(cfg: dict, func):
    from mcp import ClientSession  # type: ignore

    transport = cfg.get("transport", "stdio")
    if transport == "stdio":
        from mcp import StdioServerParameters  # type: ignore
        from mcp.client.stdio import stdio_client  # type: ignore

        env = dict(os.environ)
        env.update({k: str(v) for k, v in (cfg.get("env") or {}).items()})
        params = StdioServerParameters(
            command=cfg["command"], args=list(cfg.get("args") or []), env=env, cwd=cfg.get("cwd") or None
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await func(session)
    if transport == "sse":
        from mcp.client.sse import sse_client  # type: ignore

        async with sse_client(cfg["url"], headers=cfg.get("headers") or None) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await func(session)
    from mcp.client.streamable_http import streamablehttp_client  # type: ignore

    async with streamablehttp_client(cfg["url"], headers=cfg.get("headers") or None) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await func(session)


def _run_async(coro, timeout: float):
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


def list_mcp_tools(server_name: str) -> List[Dict[str, Any]]:
    cfg = _mcp_server_cfg(server_name)

    async def go(session):
        tools = await session.list_tools()
        return [
            {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
            for t in tools.tools
        ]

    return _run_async(_with_mcp_session(cfg, go), float(cfg.get("timeout", 120)))


def _image_from_mcp_result(result) -> Optional[bytes]:
    texts = []
    for item in getattr(result, "content", []) or []:
        itype = getattr(item, "type", "")
        if itype == "image" and getattr(item, "data", None):
            return base64.b64decode(item.data)
        if itype == "resource":
            res = item.resource
            if getattr(res, "blob", None):
                return base64.b64decode(res.blob)
            if getattr(res, "text", None):
                texts.append(res.text)
            if getattr(res, "uri", None):
                texts.append(str(res.uri))
        elif itype == "resource_link" and getattr(item, "uri", None):
            texts.append(str(item.uri))
        elif itype == "text":
            texts.append(item.text)
    structured = getattr(result, "structuredContent", None)
    if structured:
        data = bytes_from_reference(structured)
        if data:
            return data
    for text in texts:
        data = bytes_from_reference(text)
        if data:
            return data
    if getattr(result, "isError", False):
        raise RuntimeError("MCP tool error: " + " | ".join(texts)[:800])
    raise RuntimeError("MCP tool returned no image. Text output: " + " | ".join(texts)[:800])


def _mcp(server_name: str, prompt: str, aspect_ratio: str, negative_prompt: Optional[str]) -> Optional[bytes]:
    cfg = _mcp_server_cfg(server_name)
    width, height = aspect_to_size(aspect_ratio)
    values = {
        "PROMPT": prompt,
        "NEGATIVE_PROMPT": negative_prompt or "",
        "WIDTH": width,
        "HEIGHT": height,
        "ASPECT_RATIO": aspect_ratio,
        "SEED": random.randint(0, 2**31 - 1),
    }
    arguments = fill_placeholders(copy.deepcopy(cfg.get("extra_args") or {}), values)
    arguments[cfg.get("prompt_arg", "prompt")] = prompt
    tool = cfg.get("tool", "generate_image")

    async def go(session):
        return await session.call_tool(tool, arguments)

    result = _run_async(_with_mcp_session(cfg, go), float(cfg.get("timeout", 600)))
    return _image_from_mcp_result(result)


# --- generic HTTP ------------------------------------------------------------


def _http(api_name: str, prompt: str, aspect_ratio: str, negative_prompt: Optional[str]) -> Optional[bytes]:
    apis = get_setting("image.http_apis", {}) or {}
    if api_name not in apis:
        raise ValueError(f"HTTP image API '{api_name}' is not configured (Settings > Image > HTTP).")
    cfg = expand_env(apis[api_name])
    width, height = aspect_to_size(aspect_ratio)
    model = (cfg.get("body") or {}).get("model", "") if isinstance(cfg.get("body"), dict) else ""
    values = {
        "PROMPT": prompt,
        "NEGATIVE_PROMPT": negative_prompt or "",
        "WIDTH": width,
        "HEIGHT": height,
        "ASPECT_RATIO": aspect_ratio,
        "SEED": random.randint(0, 2**31 - 1),
        "OPENAI_SIZE": openai_size_for(str(model), aspect_ratio),
    }
    method = cfg.get("method", "POST").upper()
    body = fill_placeholders(copy.deepcopy(cfg.get("body")), values)
    timeout = float(cfg.get("timeout", 600))
    headers = cfg.get("headers") or {}
    rsp = requests.request(
        method,
        cfg["url"],
        headers=headers,
        json=body if method != "GET" else None,
        params=fill_placeholders(cfg.get("params"), values) if cfg.get("params") else None,
        timeout=timeout,
    )
    if rsp.status_code >= 400:
        raise RuntimeError(f"HTTP image API error {rsp.status_code}: {rsp.text[:800]}")
    if rsp.headers.get("content-type", "").startswith("image/"):
        return rsp.content
    data = rsp.json()

    poll = cfg.get("poll")
    if poll:
        deadline = time.time() + timeout
        poll_url = get_by_path(data, poll["url_path"])
        done_values = set(poll.get("done_values", ["succeeded", "completed", "done"]))
        fail_values = set(poll.get("fail_values", ["failed", "error", "canceled"]))
        while time.time() < deadline:
            status = str(get_by_path(data, poll.get("status_path", "status"))).lower()
            if status in done_values:
                break
            if status in fail_values:
                raise RuntimeError(f"HTTP image job failed: {json.dumps(data)[:800]}")
            time.sleep(float(poll.get("interval", 2)))
            data = requests.get(poll_url, headers=headers, timeout=60).json()
    value = get_by_path(data, cfg.get("response_path", "")) if cfg.get("response_path") else data
    return bytes_from_reference(value)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def generate_image_bytes(
    prompt: str,
    backend: Optional[str] = None,
    aspect_ratio: str = "16:9",
    system_instruction: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
) -> Optional[bytes]:
    kind, target = parse_backend(backend)
    if kind == "gemini":
        return _gemini(target, prompt, aspect_ratio, system_instruction)
    full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
    if kind == "openai_images":
        return _openai_images(target, full_prompt, aspect_ratio)
    if kind == "openai_chat":
        return _openai_chat_image(target, full_prompt, aspect_ratio)
    if kind == "comfyui":
        return _comfyui(target, prompt, aspect_ratio, negative_prompt, seed)
    if kind == "mcp":
        return _mcp(target, prompt, aspect_ratio, negative_prompt)
    if kind == "http":
        return _http(target, prompt, aspect_ratio, negative_prompt)
    raise ValueError(f"Unknown image backend '{backend}'")


def generate_image(
    prompt: str,
    backend: Optional[str] = None,
    aspect_ratio: str = "16:9",
    system_instruction: Optional[str] = None,
    save_path: Optional[str] = None,
    max_retries: int = 3,
    **kwargs,
) -> Optional[str]:
    """Generates an image and returns it as base64-encoded PNG (None on failure)."""
    last_error = None
    for attempt in range(max_retries):
        try:
            data = generate_image_bytes(
                prompt, backend, aspect_ratio, system_instruction, **kwargs
            )
            if data:
                data = to_png_bytes(data)
                _save(data, save_path)
                return _b64(data)
            last_error = "backend returned no image"
        except Exception as exc:
            last_error = exc
            print(f"[image] backend '{backend}' attempt {attempt + 1}/{max_retries} failed: {exc}")
            if isinstance(exc, (ValueError, FileNotFoundError)):
                break
        time.sleep(2 * attempt)
    print(f"[image] giving up on backend '{backend}': {last_error}")
    return None


def test_comfyui() -> Tuple[bool, str]:
    cfg = get_setting("image.comfyui", {}) or {}
    base = expand_env(cfg.get("base_url", "http://127.0.0.1:8188")).rstrip("/")
    try:
        stats = requests.get(f"{base}/system_stats", timeout=5).json()
        ckpts = []
        try:
            info = requests.get(f"{base}/object_info/CheckpointLoaderSimple", timeout=10).json()
            ckpts = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        except Exception:
            pass
        version = stats.get("system", {}).get("comfyui_version", "?")
        return True, f"ComfyUI {version} reachable. Checkpoints: {', '.join(ckpts[:15]) or 'n/a'}"
    except Exception as exc:
        return False, f"Cannot reach ComfyUI at {base}: {exc}"
