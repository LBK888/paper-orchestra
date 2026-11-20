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

"""Session setup: start the mock backend and point the app's settings at it.

Everything runs offline against ``tests/mock_backend.py``; no API keys are
read or sent (provider ``api_key_env`` entries are nulled in the test settings).
"""

import json
import os
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.mock_backend import MockBackend, build_test_settings  # noqa: E402

_STATE = {}
_ENV_KEYS = ("PAPER_ORCHESTRA_SETTINGS", "PYTHONUTF8", "PO_TEST_HTTP_KEY")


def pytest_configure(config):
    backend = MockBackend().start()
    tmp = tempfile.mkdtemp(prefix="po_tests_")
    settings = build_test_settings(
        base_url=backend.url,
        projects_dir=os.path.join(tmp, "projects"),
        mcp_server_script=os.path.join(ROOT, "tests", "mcp_image_server.py"),
        python=sys.executable,
    )
    settings_path = os.path.join(tmp, "settings.json")
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

    _STATE.update(backend=backend, tmp=tmp, env={k: os.environ.get(k) for k in _ENV_KEYS})
    os.environ["PAPER_ORCHESTRA_SETTINGS"] = settings_path
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PO_TEST_HTTP_KEY"] = "abc"

    from utils.settings import load_settings

    load_settings(force=True)


def pytest_unconfigure(config):
    backend = _STATE.get("backend")
    if backend:
        backend.stop()
    if _STATE.get("tmp"):
        shutil.rmtree(_STATE["tmp"], ignore_errors=True)
    for key, value in (_STATE.get("env") or {}).items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="session")
def mock_backend() -> MockBackend:
    return _STATE["backend"]


@pytest.fixture(scope="session")
def session_tmp() -> str:
    return _STATE["tmp"]
