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

"""Provider-agnostic LLM transport.

Model names use ``provider:model`` (``ollama:qwen3:32b``,
``openrouter:anthropic/claude-sonnet-4.5``, ``llamacpp:local``,
``vllm:Qwen/Qwen3-32B``, ``openai:gpt-5``, ``gemini:gemini-3.1-pro-preview``).
Names without a known provider prefix keep the legacy behaviour
(``gpt*``/``o1``/``o3``/``o4`` -> OpenAI, everything else -> Gemini).

Contents may be ``str``, ``google.genai.types.Part``, dicts such as
``{"type": "text", "text": ...}`` / ``{"type": "image", "path": ...}`` /
``{"type": "bytes", "data": b"...", "mime_type": "image/png"}``, or nested lists.
"""

import base64
import mimetypes
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from utils.settings import expand_env, load_settings

PROVIDER_ALIASES = {
    "google": "gemini",
    "vertex": "gemini",
    "llama.cpp": "llamacpp",
    "llama_cpp": "llamacpp",
    "llama-cpp": "llamacpp",
    "lm_studio": "lmstudio",
    "lm-studio": "lmstudio",
    "oai": "openai",
}

GEMINI_ONLY_CONFIG_KEYS = {
    "tools",
    "tool_config",
    "thinking_config",
    "response_modalities",
    "image_config",
    "response_mime_type",
    "response_schema",
    "safety_settings",
    "candidate_count",
    "speech_config",
    "media_resolution",
}

THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class ResolvedModel:
    provider: str
    model: str
    cfg: Dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return self.cfg.get("type", "openai_compatible")

    @property
    def spec(self) -> str:
        return f"{self.provider}:{self.model}"


def get_providers() -> Dict[str, Dict[str, Any]]:
    return load_settings().get("llm", {}).get("providers", {})


def resolve_model(model_name: str) -> ResolvedModel:
    """Maps a model spec to (provider, model id, provider config)."""
    if not model_name:
        raise ValueError("Empty model name.")
    providers = get_providers()
    if ":" in model_name:
        prefix, rest = model_name.split(":", 1)
        provider = PROVIDER_ALIASES.get(prefix.lower(), prefix.lower())
        if provider in providers:
            return ResolvedModel(provider, rest, dict(providers[provider]))

    low = model_name.lower()
    if low.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
        provider = "openai"
    elif low.startswith("gemini"):
        provider = "gemini"
    else:
        provider = load_settings().get("llm", {}).get("default_provider", "gemini")
    return ResolvedModel(provider, model_name, dict(providers.get(provider, {})))


def is_gemini(model_name: str) -> bool:
    return resolve_model(model_name).type == "gemini"


# ---------------------------------------------------------------------------
# Content normalisation
# ---------------------------------------------------------------------------


@dataclass
class NormPart:
    kind: str  # "text" | "bytes"
    text: str = ""
    data: bytes = b""
    mime_type: str = ""


def _guess_mime(path: str, default: str = "image/png") -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or default


def sniff_image_mime(data: bytes, default: str = "image/png") -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"%PDF":
        return "application/pdf"
    return default


def normalize_contents(contents: Any) -> List[NormPart]:
    parts: List[NormPart] = []

    def visit(item: Any):
        if item is None:
            return
        if isinstance(item, str):
            parts.append(NormPart("text", text=item))
        elif isinstance(item, (bytes, bytearray)):
            data = bytes(item)
            parts.append(NormPart("bytes", data=data, mime_type=sniff_image_mime(data)))
        elif isinstance(item, (list, tuple)):
            for sub in item:
                visit(sub)
        elif isinstance(item, dict):
            itype = item.get("type", "text")
            if itype == "text":
                parts.append(NormPart("text", text=str(item.get("text", ""))))
            elif itype in ("image", "file") and item.get("path"):
                with open(item["path"], "rb") as f:
                    data = f.read()
                mime = item.get("mime_type") or _guess_mime(item["path"])
                parts.append(NormPart("bytes", data=data, mime_type=mime))
            elif itype in ("bytes", "image", "file"):
                data = item.get("data", b"")
                if isinstance(data, str):
                    data = base64.b64decode(data)
                mime = item.get("mime_type") or sniff_image_mime(data)
                parts.append(NormPart("bytes", data=data, mime_type=mime))
            elif itype == "image_url":
                url = item.get("image_url", {}).get("url", "")
                if url.startswith("data:"):
                    header, b64 = url.split(",", 1)
                    mime = header[5:].split(";")[0]
                    parts.append(
                        NormPart("bytes", data=base64.b64decode(b64), mime_type=mime)
                    )
        elif hasattr(item, "parts") and getattr(item, "parts", None) is not None:
            visit(list(item.parts))  # google.genai types.Content
        else:
            # google.genai types.Part
            text = getattr(item, "text", None)
            inline = getattr(item, "inline_data", None)
            if text is not None:
                parts.append(NormPart("text", text=text))
            elif inline is not None and getattr(inline, "data", None) is not None:
                parts.append(
                    NormPart(
                        "bytes",
                        data=inline.data,
                        mime_type=inline.mime_type or sniff_image_mime(inline.data),
                    )
                )
            else:
                parts.append(NormPart("text", text=str(item)))

    visit(contents)
    return parts


def pdf_bytes_to_text(data: bytes) -> str:
    try:
        import pymupdf  # type: ignore

        doc = pymupdf.open(stream=data, filetype="pdf")
        return "".join(page.get_text() for page in doc)
    except Exception as exc:  # pragma: no cover - best effort
        return f"[PDF text extraction failed: {exc}]"


def to_gemini_contents(contents: Any) -> list:
    """Converts any supported content representation into genai Parts."""
    from google.genai import types  # type: ignore

    out = []
    for part in normalize_contents(contents):
        if part.kind == "text":
            out.append(types.Part.from_text(text=part.text))
        else:
            out.append(types.Part.from_bytes(data=part.data, mime_type=part.mime_type))
    return out


def _openai_user_content(parts: List[NormPart], supports_vision: bool):
    content: list = []
    has_image = False
    for part in parts:
        if part.kind == "text":
            content.append({"type": "text", "text": part.text})
        elif part.mime_type == "application/pdf":
            content.append(
                {
                    "type": "text",
                    "text": "[Attached PDF converted to text]\n"
                    + pdf_bytes_to_text(part.data),
                }
            )
        elif part.mime_type.startswith("image/"):
            if supports_vision:
                b64 = base64.b64encode(part.data).decode("utf-8")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{part.mime_type};base64,{b64}"},
                    }
                )
                has_image = True
            else:
                content.append(
                    {
                        "type": "text",
                        "text": "[An image was attached here but the configured model has no vision support; "
                        "rely on the textual description instead.]",
                    }
                )
        else:
            try:
                content.append({"type": "text", "text": part.data.decode("utf-8")})
            except UnicodeDecodeError:
                pass
    if not has_image:
        return "\n\n".join(c["text"] for c in content)
    return content


# ---------------------------------------------------------------------------
# Clients and concurrency
# ---------------------------------------------------------------------------

_client_cache: Dict[Tuple, Any] = {}
_client_lock = threading.Lock()
_semaphores: Dict[str, threading.BoundedSemaphore] = {}
_sem_lock = threading.Lock()


def provider_api_key(cfg: Dict[str, Any]) -> Optional[str]:
    env_name = cfg.get("api_key_env")
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    key = cfg.get("api_key")
    return expand_env(key) if key else None


def _get_openai_client(provider: str, cfg: Dict[str, Any]):
    from openai import OpenAI  # type: ignore

    base_url = expand_env(cfg.get("base_url") or "")
    if not base_url:
        raise ValueError(
            f"Provider '{provider}' has no base_url configured (Settings > LLM providers)."
        )
    api_key = provider_api_key(cfg)
    if not api_key:
        raise ValueError(
            f"Provider '{provider}' needs an API key: set {cfg.get('api_key_env') or 'api_key'} "
            "in .env or in Settings."
        )
    headers = expand_env(cfg.get("extra_headers") or {}) or None
    timeout = float(cfg.get("timeout") or 900)
    key = (provider, base_url, api_key, timeout, tuple(sorted((headers or {}).items())))
    with _client_lock:
        if key not in _client_cache:
            _client_cache[key] = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
                max_retries=0,
                default_headers=headers,
            )
        return _client_cache[key]


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def provider_slot(provider: str, cfg: Dict[str, Any]):
    limit = cfg.get("max_concurrency")
    if not limit:
        return _NullContext()
    with _sem_lock:
        if provider not in _semaphores:
            _semaphores[provider] = threading.BoundedSemaphore(int(limit))
        return _semaphores[provider]


# ---------------------------------------------------------------------------
# Single-shot calls (no retry; retry lives in llm_backend_utils)
# ---------------------------------------------------------------------------


def strip_thinking(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    text = THINK_PATTERN.sub("", text)
    if "</think>" in text:  # opening tag consumed by the chat template
        text = text.split("</think>", 1)[1]
    return text.strip()


def _split_generation_configs(generation_configs: Optional[Dict[str, Any]]):
    cfg = dict(generation_configs or {})
    system = cfg.pop("system_instruction", None)
    if system is not None and not isinstance(system, str):
        system = "\n".join(p.text for p in normalize_contents(system) if p.kind == "text")
    for k in list(cfg):
        if k in GEMINI_ONLY_CONFIG_KEYS:
            cfg.pop(k)
    if "max_output_tokens" in cfg:
        cfg["max_tokens"] = cfg.pop("max_output_tokens")
    return system, cfg


def _is_reasoning_openai_model(model: str) -> bool:
    return model.lower().startswith(("o1", "o3", "o4", "gpt-5"))


def call_openai_compatible(
    resolved: ResolvedModel,
    contents: Any,
    generation_configs: Optional[Dict[str, Any]] = None,
) -> str:
    cfg = resolved.cfg
    system, gen = _split_generation_configs(generation_configs)
    parts = normalize_contents(contents)
    user_content = _openai_user_content(parts, bool(cfg.get("supports_vision", False)))

    messages = []
    if system:
        role = cfg.get("system_role", "system")
        if role == "developer" and not _is_reasoning_openai_model(resolved.model):
            role = "system"
        messages.append({"role": role, "content": system})
    messages.append({"role": "user", "content": user_content})

    params: Dict[str, Any] = {}
    allowed = {"temperature", "top_p", "max_tokens", "seed", "stop", "presence_penalty", "frequency_penalty"}
    for k, v in gen.items():
        if k in allowed and v is not None:
            params[k] = v
    if cfg.get("drop_temperature") or (
        resolved.provider == "openai" and _is_reasoning_openai_model(resolved.model)
    ):
        params.pop("temperature", None)
        params.pop("top_p", None)
    if cfg.get("max_tokens") and "max_tokens" not in params:
        params["max_tokens"] = cfg["max_tokens"]
    if resolved.provider == "openai" and "max_tokens" in params:
        params["max_completion_tokens"] = params.pop("max_tokens")
    extra_body = cfg.get("extra_body") or None

    client = _get_openai_client(resolved.provider, cfg)
    with provider_slot(resolved.provider, cfg):
        response = client.chat.completions.create(
            model=resolved.model,
            messages=messages,
            extra_body=extra_body,
            **params,
        )
    if not response.choices:
        raise ValueError(f"Empty response from {resolved.spec}")
    text = response.choices[0].message.content
    if not text:
        raise ValueError(
            f"Empty message content from {resolved.spec} "
            f"(finish_reason={response.choices[0].finish_reason})"
        )
    return strip_thinking(text)


def call_ollama(
    resolved: ResolvedModel,
    contents: Any,
    generation_configs: Optional[Dict[str, Any]] = None,
) -> str:
    cfg = resolved.cfg
    system, gen = _split_generation_configs(generation_configs)
    parts = normalize_contents(contents)
    supports_vision = bool(cfg.get("supports_vision", False))

    texts: List[str] = []
    images: List[str] = []
    for part in parts:
        if part.kind == "text":
            texts.append(part.text)
        elif part.mime_type == "application/pdf":
            texts.append("[Attached PDF converted to text]\n" + pdf_bytes_to_text(part.data))
        elif part.mime_type.startswith("image/"):
            if supports_vision:
                images.append(base64.b64encode(part.data).decode("utf-8"))
            else:
                texts.append(
                    "[An image was attached here but the configured model has no vision support.]"
                )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    user_msg: Dict[str, Any] = {"role": "user", "content": "\n\n".join(texts)}
    if images:
        user_msg["images"] = images
    messages.append(user_msg)

    options: Dict[str, Any] = {}
    if cfg.get("num_ctx"):
        options["num_ctx"] = int(cfg["num_ctx"])
    if gen.get("temperature") is not None:
        options["temperature"] = gen["temperature"]
    if gen.get("top_p") is not None:
        options["top_p"] = gen["top_p"]
    if gen.get("max_tokens"):
        options["num_predict"] = gen["max_tokens"]
    if gen.get("seed") is not None:
        options["seed"] = gen["seed"]
    options.update(cfg.get("options") or {})

    payload: Dict[str, Any] = {
        "model": resolved.model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    if cfg.get("keep_alive"):
        payload["keep_alive"] = cfg["keep_alive"]
    if cfg.get("think") is not None:
        payload["think"] = bool(cfg["think"])

    base_url = expand_env(cfg.get("base_url") or "http://localhost:11434").rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    headers = {}
    api_key = provider_api_key(cfg)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with provider_slot(resolved.provider, cfg):
        rsp = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            headers=headers,
            timeout=float(cfg.get("timeout") or 3600),
        )
    if rsp.status_code != 200:
        raise RuntimeError(f"Ollama error {rsp.status_code}: {rsp.text[:500]}")
    data = rsp.json()
    text = (data.get("message") or {}).get("content", "")
    if not text:
        raise ValueError(f"Empty response from {resolved.spec}: {str(data)[:300]}")
    return strip_thinking(text)


def is_non_retryable(exc: Exception) -> bool:
    name = type(exc).__name__
    if name in ("BadRequestError", "AuthenticationError", "PermissionDeniedError", "NotFoundError"):
        return True
    msg = str(exc).lower()
    return any(
        s in msg
        for s in (
            "maximum context length",
            "context length",
            "context_length_exceeded",
            "maximum number of tokens allowed",
            "400 invalid_argument",
            "needs an api key",
            "no base_url configured",
        )
    )


# ---------------------------------------------------------------------------
# Discovery helpers (used by the UI)
# ---------------------------------------------------------------------------


def list_models(provider: str, timeout: float = 10) -> List[str]:
    providers = get_providers()
    if provider not in providers:
        raise ValueError(f"Unknown provider '{provider}'")
    cfg = providers[provider]
    ptype = cfg.get("type")
    if ptype == "gemini":
        from utils.gemini_utils import get_genai_client

        client = get_genai_client()
        return sorted(m.name.replace("models/", "") for m in client.models.list())
    if ptype == "ollama":
        base_url = expand_env(cfg.get("base_url") or "http://localhost:11434").rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        rsp = requests.get(f"{base_url}/api/tags", timeout=timeout)
        rsp.raise_for_status()
        return sorted(m["name"] for m in rsp.json().get("models", []))
    base_url = expand_env(cfg.get("base_url") or "").rstrip("/")
    headers = {}
    api_key = provider_api_key(cfg)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    rsp = requests.get(f"{base_url}/models", headers=headers, timeout=timeout)
    rsp.raise_for_status()
    data = rsp.json()
    items = data.get("data", data if isinstance(data, list) else [])
    return sorted(str(m.get("id")) for m in items if isinstance(m, dict) and m.get("id"))


def ping_model(model_name: str) -> Tuple[bool, str, float]:
    """Sends a tiny prompt; returns (ok, reply_or_error, seconds)."""
    from utils.llm_backend_utils import call_llm_with_contents

    t0 = time.time()
    try:
        rsp = call_llm_with_contents(
            contents=["Reply with exactly: OK"],
            model_name=model_name,
            generation_configs={"temperature": 0},
            return_json=False,
            check_parsed_response_not_none=False,
            max_retries=1,
        )
        return True, str(rsp.get("raw_response", ""))[:200], time.time() - t0
    except Exception as exc:
        return False, str(exc)[:500], time.time() - t0
