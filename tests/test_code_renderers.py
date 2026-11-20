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

"""Code-based figure rendering: matplotlib, seaborn, plotly, graphviz, Remotion."""

import os

import pytest

from tests.mock_backend import REMOTION_SAMPLE
from utils.code_renderers import (
    engine_available,
    extract_code,
    remotion_status,
    render_graphviz,
    render_python,
    render_remotion,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _is_png(path):
    with open(path, "rb") as f:
        return f.read(8) == PNG_MAGIC


def test_extract_code_prefers_requested_language():
    text = "intro\n```bash\nls\n```\n```python\nprint(1)\n```"
    assert extract_code(text, ["python"]) == "print(1)"
    assert extract_code("```\nraw\n```", ["tsx"]) == "raw"
    assert extract_code("just code", ["python"]) == "just code"


def test_matplotlib_hardcoded_savefig_is_redirected(tmp_path):
    out = tmp_path / "mpl.png"
    res = render_python("import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\nplt.savefig('foo.png')", str(out))
    assert res.ok, res.error
    assert _is_png(out)


def test_seaborn_figure_is_auto_saved(tmp_path):
    out = tmp_path / "sns.png"
    code = (
        "import seaborn as sns, pandas as pd\n"
        "df = pd.DataFrame({'x': ['a', 'b'], 'y': [1, 2]})\n"
        "sns.barplot(data=df, x='x', y='y')\n"
    )
    res = render_python(code, str(out))
    assert res.ok, res.error
    assert _is_png(out)


def test_python_errors_are_reported(tmp_path):
    res = render_python("raise ValueError('boom')", str(tmp_path / "bad.png"))
    assert not res.ok
    assert "boom" in res.error


def test_script_without_figure_fails(tmp_path):
    res = render_python("x = 1", str(tmp_path / "none.png"))
    assert not res.ok
    assert "no figure" in res.error


def test_python_render_timeout(tmp_path):
    res = render_python("import time\ntime.sleep(30)", str(tmp_path / "slow.png"), timeout=3)
    assert not res.ok
    assert "Timed out" in res.error


@pytest.mark.skipif(not engine_available("plotly"), reason="plotly/kaleido not installed")
def test_plotly_static_export(tmp_path):
    out = tmp_path / "plotly.png"
    res = render_python("import plotly.express as px\nfig = px.bar(x=['a', 'b'], y=[1, 2])", str(out))
    if not res.ok and "chrome" in res.error.lower():
        pytest.skip("kaleido needs Chrome: run `python -c \"import kaleido; kaleido.get_chrome_sync()\"`")
    assert res.ok, res.error
    assert _is_png(out)


@pytest.mark.skipif(not engine_available("graphviz"), reason="Graphviz 'dot' not on PATH")
def test_graphviz_render(tmp_path):
    out = tmp_path / "g.png"
    res = render_graphviz('digraph G { rankdir=LR; a -> b -> c; }', str(out))
    assert res.ok, res.error
    assert _is_png(out)


def test_graphviz_missing_binary_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.code_renderers.shutil.which", lambda name: None)
    res = render_graphviz("digraph { a -> b }", str(tmp_path / "g.png"))
    assert not res.ok and "not found" in res.error


@pytest.mark.slow
@pytest.mark.skipif(not remotion_status()["ready"], reason="Node.js + tools/remotion not installed")
def test_remotion_still_and_animation(tmp_path):
    with open(REMOTION_SAMPLE, "r", encoding="utf-8") as f:
        code = f.read()
    out = tmp_path / "remotion.png"
    res = render_remotion(code, str(out), "pytest_sample", render_animation=True)
    assert res.ok, res.error[-1500:]
    assert _is_png(out)
    assert res.animation_path and os.path.getsize(res.animation_path) > 1000, res.extra
