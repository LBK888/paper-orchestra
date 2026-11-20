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

"""Unified LLM entry points used by every agent.

All functions accept a model spec understood by ``utils.llm_providers``:
``gemini:...``, ``openai:...``, ``openrouter:...``, ``ollama:...``,
``llamacpp:...``, ``vllm:...``, ``lmstudio:...``, ``custom:...`` or a bare
legacy model name.
"""

import mimetypes
import time
from typing import Any, Callable, Dict, Optional

import json_repair

from utils.gemini_utils import call_gemini_with_contents, parse_gemini_json_results
from utils.openai_utils import parse_openai_json_results
from utils.llm_providers import (
    call_ollama,
    call_openai_compatible,
    is_non_retryable,
    resolve_model,
    strip_thinking,
    to_gemini_contents,
)


def identity_parse(response: str):
    return response


def parse_json_results(response: str):
    """Robust JSON extraction (fenced block, bare object/array, json_repair)."""
    if not response or not isinstance(response, str):
        return None
    response = strip_thinking(response)
    parsed = parse_openai_json_results(response)
    if parsed is not None:
        return parsed
    try:
        start = min(
            [i for i in (response.find("{"), response.find("[")) if i != -1],
            default=-1,
        )
        if start == -1:
            return None
        repaired = json_repair.loads(response[start:])
        if isinstance(repaired, (dict, list)) and repaired:
            return repaired
    except Exception:
        pass
    return None


def get_llm_parser(model_name: str, return_json: bool = True) -> Callable:
    if not return_json:
        return identity_parse
    if resolve_model(model_name).type == "gemini":
        return parse_gemini_json_results
    return parse_json_results


def call_llm_with_contents(
    contents: Any,
    model_name: str,
    generation_configs: Optional[Dict[str, Any]] = None,
    result_parsing_func: Optional[Callable] = None,
    check_parsed_response_not_none: bool = True,
    return_json: bool = True,
    max_retries: int = 5,
    base_interval_sec: int = 5,
) -> Dict[str, Any]:
    """Provider-agnostic multimodal call with retry and result parsing.

    Returns ``{"raw_response": str, "parsed_response": Any}`` like the legacy
    Gemini/OpenAI helpers.
    """
    resolved = resolve_model(model_name)
    parser = (
        result_parsing_func
        if result_parsing_func is not None
        else get_llm_parser(model_name, return_json)
    )
    generation_configs = dict(generation_configs or {})

    if resolved.type == "gemini":
        return call_gemini_with_contents(
            contents=to_gemini_contents(contents),
            model_name=resolved.model,
            generation_configs=generation_configs,
            result_parsing_func=parser,
            check_parsed_response_not_none=check_parsed_response_not_none,
            max_retries=max_retries,
            base_interval_sec=base_interval_sec,
        )

    if resolved.type == "ollama":
        transport = call_ollama
    elif resolved.type == "openai_compatible":
        transport = call_openai_compatible
    else:
        raise ValueError(
            f"Unsupported provider type '{resolved.type}' for model '{model_name}'"
        )

    raw_response = None
    parsed_response = None
    for attempt in range(max_retries):
        try:
            raw_response = transport(resolved, contents, generation_configs)
            parsed_response = parser(raw_response)
            if check_parsed_response_not_none:
                assert (
                    parsed_response is not None
                ), f"Parsed response is None, here is the raw response:\n{raw_response}"
            return {"raw_response": raw_response, "parsed_response": parsed_response}
        except Exception as e:
            print(
                f"Warning: LLM call ({resolved.spec}) failed on attempt "
                f"{attempt + 1}/{max_retries}. Error: {str(e)[:500]}"
            )
            if is_non_retryable(e) or attempt + 1 == max_retries:
                raise
            delay = base_interval_sec * (2 ** (attempt - 1)) if attempt > 0 else 0
            if delay > 0:
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)

    return {"raw_response": raw_response, "parsed_response": parsed_response}


def call_llm_with_text_prompt(
    prompt: str,
    model_name: str,
    generation_configs: Optional[Dict[str, Any]] = None,
    check_parsed_response_not_none: bool = True,
    return_json: bool = True,
    result_parsing_func: Optional[Callable] = None,
) -> Dict[str, Any]:
    return call_llm_with_contents(
        contents=[prompt],
        model_name=model_name,
        generation_configs=generation_configs,
        result_parsing_func=result_parsing_func,
        check_parsed_response_not_none=check_parsed_response_not_none,
        return_json=return_json,
    )


def call_llm_with_images(
    prompt: str,
    images: list[str],
    model_name: str,
    generation_configs: Optional[Dict[str, Any]] = None,
    check_parsed_response_not_none: bool = True,
    return_json: bool = True,
    result_parsing_func: Optional[Callable] = None,
) -> Dict[str, Any]:
    contents: list = [prompt]
    for image_path in images:
        mime, _ = mimetypes.guess_type(image_path)
        contents.append({"type": "image", "path": image_path, "mime_type": mime or "image/png"})
    return call_llm_with_contents(
        contents=contents,
        model_name=model_name,
        generation_configs=generation_configs,
        result_parsing_func=result_parsing_func,
        check_parsed_response_not_none=check_parsed_response_not_none,
        return_json=return_json,
    )


def call_llm_with_pdf(
    pdf_path: str,
    prompt: str,
    model_name: str,
    system_instruction: Optional[str] = None,
    temperature: float = 0.7,
    check_parsed_response_not_none: bool = True,
    return_json: bool = True,
    result_parsing_func: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Gemini receives raw PDF bytes; other providers receive extracted text."""
    if resolve_model(model_name).type == "gemini":
        with open(pdf_path, "rb") as f:
            contents = [
                {"type": "bytes", "data": f.read(), "mime_type": "application/pdf"},
                prompt,
            ]
    else:
        from utils.pdf_utils import load_paper

        contents = [f"Paper Content:\n{load_paper(pdf_path, min_size=100)}\n\nTask:\n{prompt}"]

    generation_configs: Dict[str, Any] = {"temperature": temperature}
    if system_instruction is not None:
        generation_configs["system_instruction"] = system_instruction
    return call_llm_with_contents(
        contents=contents,
        model_name=model_name,
        generation_configs=generation_configs,
        result_parsing_func=result_parsing_func,
        check_parsed_response_not_none=check_parsed_response_not_none,
        return_json=return_json,
    )
