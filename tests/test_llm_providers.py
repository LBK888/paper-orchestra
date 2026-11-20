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

"""Provider routing, request shaping and response parsing for every LLM backend."""

import pytest
from google.genai import types
from PIL import Image

from utils.llm_backend_utils import (
    call_llm_with_contents,
    call_llm_with_images,
    call_llm_with_text_prompt,
    parse_json_results,
)
from utils.llm_providers import list_models, ping_model, resolve_model, strip_thinking, to_gemini_contents

OUTLINE_PROMPT = (
    'You must output a single, valid JSON object with the following three top-level keys: '
    '"plotting_plan", "intro_related_work_plan", and "section_plan".'
)


@pytest.mark.parametrize(
    "spec, provider, ptype, model",
    [
        ("ollama:qwen3:32b", "ollama", "ollama", "qwen3:32b"),
        ("openrouter:anthropic/claude-sonnet-4.5", "openrouter", "openai_compatible", "anthropic/claude-sonnet-4.5"),
        ("llamacpp:local", "llamacpp", "openai_compatible", "local"),
        ("llama.cpp:x", "llamacpp", "openai_compatible", "x"),
        ("vllm:Qwen/Qwen3-32B", "vllm", "openai_compatible", "Qwen/Qwen3-32B"),
        ("lmstudio:qwen2.5", "lmstudio", "openai_compatible", "qwen2.5"),
        ("custom:foo", "custom", "openai_compatible", "foo"),
        ("gemini:gemini-3-flash-preview", "gemini", "gemini", "gemini-3-flash-preview"),
        # legacy, un-prefixed names keep their original routing
        ("gpt-5", "openai", "openai_compatible", "gpt-5"),
        ("o3-mini", "openai", "openai_compatible", "o3-mini"),
        ("gemini-3.1-pro-preview", "gemini", "gemini", "gemini-3.1-pro-preview"),
    ],
)
def test_resolve_model(spec, provider, ptype, model):
    resolved = resolve_model(spec)
    assert (resolved.provider, resolved.type, resolved.model) == (provider, ptype, model)


def test_unprefixed_unknown_name_uses_default_provider():
    # test settings set default_provider=llamacpp
    assert resolve_model("some-local-model").provider == "llamacpp"


@pytest.mark.parametrize(
    "spec",
    ["llamacpp:mock-model", "vllm:mock-model", "lmstudio:mock-model",
     "openrouter:mock/model", "custom:mock-model", "ollama:qwen3:mock"],
)
def test_ping_every_provider_and_strip_think_tags(mock_backend, spec):
    ok, reply, _ = ping_model(spec)
    assert ok, reply
    assert reply == "OK"  # the mock prefixes <think>...</think>


def test_ollama_native_api_parses_json_and_sends_num_ctx(mock_backend):
    rsp = call_llm_with_text_prompt(OUTLINE_PROMPT, "ollama:qwen3:mock")
    assert "plotting_plan" in rsp["parsed_response"]
    body = mock_backend.last("/api/chat")["body"]
    assert body["options"]["num_ctx"] == 16384
    assert body["stream"] is False


def _png(tmp_path):
    path = tmp_path / "x.png"
    Image.new("RGB", (32, 32), "blue").save(path)
    return str(path)


def test_vision_provider_sends_image(mock_backend, tmp_path):
    rsp = call_llm_with_images("Reply with exactly: OK", [_png(tmp_path)], "vllm:mock-model", return_json=False)
    assert rsp["raw_response"] == "OK"
    content = mock_backend.last("/v1/chat/completions", model="mock-model")["body"]["messages"][-1]["content"]
    assert isinstance(content, list)
    assert any(c["type"] == "image_url" and c["image_url"]["url"].startswith("data:image/png;base64,") for c in content)


def test_non_vision_provider_replaces_image_with_note(mock_backend, tmp_path):
    rsp = call_llm_with_images("Reply with exactly: OK", [_png(tmp_path)], "llamacpp:mock-model", return_json=False)
    assert rsp["raw_response"] == "OK"
    content = mock_backend.last("/v1/chat/completions", model="mock-model")["body"]["messages"][-1]["content"]
    assert isinstance(content, str) and "no vision support" in content


def test_genai_parts_and_generation_config_mapping(mock_backend, tmp_path):
    with open(_png(tmp_path), "rb") as f:
        png = f.read()
    rsp = call_llm_with_contents(
        [types.Part.from_text(text="Reply with exactly: OK"), types.Part.from_bytes(data=png, mime_type="image/png")],
        "openrouter:mock/model",
        generation_configs={"system_instruction": "be brief", "temperature": 0.2, "max_output_tokens": 99,
                            "tools": ["google_search"], "thinking_config": {}},
        return_json=False,
    )
    assert rsp["raw_response"] == "OK"
    body = mock_backend.last("/v1/chat/completions", model="mock/model")["body"]
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 99
    assert "tools" not in body and "thinking_config" not in body


def test_openai_reasoning_model_drops_temperature(mock_backend):
    call_llm_with_contents(["Reply with exactly: OK"], "openai:o3-mini",
                           generation_configs={"temperature": 0.7, "system_instruction": "s"}, return_json=False)
    body = mock_backend.last("/v1/chat/completions", model="o3-mini")["body"]
    assert "temperature" not in body
    assert body["messages"][0]["role"] == "developer"


def test_list_models(mock_backend):
    assert "mock-model" in list_models("llamacpp")
    assert "qwen3:mock" in list_models("ollama")


def test_parse_json_results_is_robust():
    assert parse_json_results('<think>x</think>```json\n{"a": 1, "b": [1, 2,],}\n```') == {"a": 1, "b": [1, 2]}
    assert parse_json_results('Sure! {"index": 3, "reason": "ok"} hope it helps') == {"index": 3, "reason": "ok"}
    assert parse_json_results("no json here") is None


def test_strip_thinking_handles_unclosed_open_tag():
    assert strip_thinking("<think>a</think> answer") == "answer"
    assert strip_thinking("reasoning only closed</think>final") == "final"


def test_to_gemini_contents_accepts_every_shape():
    parts = to_gemini_contents([
        "hello",
        types.Part.from_text(text="part"),
        {"type": "bytes", "data": b"%PDF-1.4 x", "mime_type": "application/pdf"},
        {"type": "text", "text": "dict"},
        [types.Part.from_bytes(data=b"\x89PNG\r\n\x1a\nxx", mime_type="image/png")],
    ])
    summary = [(p.text, p.inline_data.mime_type if p.inline_data else None) for p in parts]
    assert summary == [("hello", None), ("part", None), (None, "application/pdf"), ("dict", None), (None, "image/png")]
