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

"""Central settings store.

``config/settings.default.json`` ships with the repo; user overrides live in
``config/settings.json`` (git-ignored) and are deep-merged on top. Secrets are
kept in ``.env`` and referenced by name (``api_key_env``) or ``${VAR}``.
"""

import copy
import json
import os
import re
import threading
from typing import Any, Optional

from dotenv import load_dotenv, set_key

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_SETTINGS_PATH = os.path.join(ROOT_DIR, "config", "settings.default.json")
ENV_PATH = os.path.join(ROOT_DIR, ".env")

load_dotenv(ENV_PATH)

_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_key = None


def user_settings_path() -> str:
    return os.environ.get(
        "PAPER_ORCHESTRA_SETTINGS",
        os.path.join(ROOT_DIR, "config", "settings.json"),
    )


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(base.get(key), value) if key in base else value
        return merged
    return copy.deepcopy(override)


def _read_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _mtime(path: str):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def load_settings(force: bool = False) -> dict:
    """Returns merged settings (defaults + user overrides). Cached by mtime."""
    global _cache, _cache_key
    user_path = user_settings_path()
    key = (_mtime(DEFAULT_SETTINGS_PATH), user_path, _mtime(user_path))
    with _lock:
        if force or _cache is None or _cache_key != key:
            merged = deep_merge(_read_json(DEFAULT_SETTINGS_PATH), _read_json(user_path))
            _cache, _cache_key = merged, key
        return copy.deepcopy(_cache)


def load_user_overrides() -> dict:
    return _read_json(user_settings_path())


def save_settings(settings: dict) -> str:
    """Persists the full settings dict as user overrides."""
    path = user_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)
    load_settings(force=True)
    return path


def get_setting(dotted_path: str, default: Any = None) -> Any:
    node: Any = load_settings()
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: Any) -> Any:
    """Recursively replaces ``${VAR}`` with environment values."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


def set_env_var(name: str, value: str) -> None:
    """Writes/updates a key in .env and the current process environment."""
    if not os.path.exists(ENV_PATH):
        open(ENV_PATH, "a", encoding="utf-8").close()
    set_key(ENV_PATH, name, value, quote_mode="never")
    os.environ[name] = value


def resolve_path(path: str) -> str:
    """Resolves a path relative to the repository root."""
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(ROOT_DIR, path)
