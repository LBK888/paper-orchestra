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

"""Image-generation backends: ComfyUI, OpenAI-compatible, OpenRouter, MCP, HTTP."""

import base64

import pytest

from utils.image_backends import (
    aspect_to_size,
    bytes_from_reference,
    fill_placeholders,
    generate_image,
    get_by_path,
    list_mcp_tools,
    openai_size_for,
    parse_backend,
    test_comfyui as comfyui_check,  # aliased so pytest does not collect it as a test
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_fill_placeholders_keeps_types():
    out = fill_placeholders(
        {"w": "{{WIDTH}}", "t": "a {{PROMPT}} b", "nested": ["{{SEED}}"], "keep": "{{UNKNOWN}}"},
        {"WIDTH": 1024, "PROMPT": "cat", "SEED": 7},
    )
    assert out == {"w": 1024, "t": "a cat b", "nested": [7], "keep": "{{UNKNOWN}}"}


@pytest.mark.parametrize("ratio", ["16:9", "1:1", "4:3", "9:16", "21:9"])
def test_aspect_to_size_is_multiple_of_64(ratio):
    w, h = aspect_to_size(ratio)
    assert w % 64 == 0 and h % 64 == 0
    assert 0.7e6 < w * h < 1.4e6


def test_openai_size_mapping():
    assert openai_size_for("gpt-image-1", "16:9") == "1536x1024"
    assert openai_size_for("dall-e-3", "9:16") == "1024x1792"
    assert openai_size_for("dall-e-2", "16:9") == "1024x1024"


def test_get_by_path_and_reference_decoding():
    assert get_by_path({"a": [{"b": 5}]}, "a.0.b") == 5
    data_url = "data:image/png;base64," + base64.b64encode(PNG_MAGIC + b"x").decode()
    assert bytes_from_reference(data_url).startswith(PNG_MAGIC)
    raw_b64 = base64.b64encode(PNG_MAGIC + b"x" * 300).decode()
    assert bytes_from_reference({"b64_json": raw_b64}).startswith(PNG_MAGIC)
    assert bytes_from_reference([{"url": data_url}]).startswith(PNG_MAGIC)


@pytest.mark.parametrize(
    "spec, kind",
    [
        ("gemini-3-pro-image-preview", "gemini"),
        ("gemini:gemini-3-pro-image-preview", "gemini"),
        ("openai:gpt-image-1", "openai_images"),
        ("openrouter:google/gemini-2.5-flash-image", "openai_chat"),
        ("comfyui", "comfyui"),
        ("comfyui:my_flux.json", "comfyui"),
        ("mcp:server", "mcp"),
        ("http:api", "http"),
    ],
)
def test_parse_backend(spec, kind):
    assert parse_backend(spec)[0] == kind


def test_comfyui_connection_check(mock_backend):
    ok, msg = comfyui_check()
    assert ok, msg
    assert "mock.safetensors" in msg


@pytest.mark.parametrize(
    "backend",
    ["comfyui", "custom:gpt-image-1", "openrouter:mock/image", "http:mockapi", "mcp:mock", "mcp:mock-text"],
)
def test_backend_returns_png(mock_backend, backend):
    b64 = generate_image("A diagram of boxes", backend=backend, aspect_ratio="16:9", max_retries=1)
    assert b64, f"{backend} returned nothing"
    assert base64.b64decode(b64)[:8] == PNG_MAGIC


def test_comfyui_workflow_gets_typed_values_and_condensed_prompt(mock_backend):
    generate_image("A very long figure description " * 20, backend="comfyui", aspect_ratio="16:9", max_retries=1)
    graph = mock_backend.last("/prompt")["body"]["prompt"]
    assert graph["5"]["inputs"]["width"] == 1344 and graph["5"]["inputs"]["height"] == 768
    assert isinstance(graph["3"]["inputs"]["seed"], int)
    assert graph["6"]["inputs"]["text"].startswith("flat vector")  # condensed by the fast LLM
    assert graph["4"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"


def test_http_api_templates_body_and_env_headers(mock_backend):
    generate_image("hello", backend="http:mockapi", aspect_ratio="16:9", max_retries=1)
    req = mock_backend.last("/gen-image")
    assert req["body"] == {"text": "hello", "w": 1344, "h": 768}
    assert req["headers"].get("Authorization") == "Bearer abc"


def test_list_mcp_tools(mock_backend):
    names = {t["name"] for t in list_mcp_tools("mock")}
    assert {"generate_image", "generate_image_url"} <= names


def test_unknown_mcp_server_fails_fast():
    assert generate_image("x", backend="mcp:does-not-exist", max_retries=3) is None
