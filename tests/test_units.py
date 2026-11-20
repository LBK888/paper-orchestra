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

"""Fast unit tests for pure helpers (no network, no subprocess)."""

import json
import os

import pytest

from methods.agents.manual_revision_agent import list_sections, unified_diff
from methods.pipeline import stage_range
from utils.run_status import StatusWriter, effective_state, read_status
from utils.settings import deep_merge, expand_env


def test_stage_range():
    assert stage_range() == ["outline", "literature", "figures", "sections", "refinement"]
    assert stage_range("sections", "sections") == ["sections"]
    with pytest.raises(ValueError):
        stage_range("refinement", "outline")
    with pytest.raises(ValueError):
        stage_range("nope")


def test_list_sections_spans():
    tex = (
        "\\begin{document}\\begin{abstract}A\\end{abstract}\n"
        "\\section{Intro}x\n\\section{Method with \\emph{math}}y\n"
        "\\bibliography{refs}\n\\end{document}"
    )
    sections = list_sections(tex)
    assert [s.title for s in sections] == ["Abstract", "Intro", "Method with \\emph{math}"]
    last = sections[-1]
    assert tex[last.start:last.end].rstrip().endswith("y")  # stops before \bibliography


def test_unified_diff():
    assert "+b" in unified_diff("a\n", "b\n")
    assert unified_diff("same\n", "same\n") == ""


def test_deep_merge_and_null_override():
    base = {"a": {"x": 1, "y": 2}, "k": "OPENAI_API_KEY"}
    assert deep_merge(base, {"a": {"y": 3}, "k": None}) == {"a": {"x": 1, "y": 3}, "k": None}
    assert base["a"]["y"] == 2  # input not mutated


def test_expand_env(monkeypatch):
    monkeypatch.setenv("PO_UNIT_VAR", "v")
    assert expand_env({"h": ["Bearer ${PO_UNIT_VAR}"], "n": 1}) == {"h": ["Bearer v"], "n": 1}
    assert expand_env("${PO_UNIT_MISSING}") == ""


def test_status_writer_lifecycle(tmp_path):
    w = StatusWriter(str(tmp_path), job="pipeline", stages=["a", "b"])
    w.stage("a", "running")
    assert effective_state(read_status(str(tmp_path))) == "running"  # this process is alive
    w.stage("a", "done")
    w.finish("done")
    data = read_status(str(tmp_path))
    assert data["state"] == "done" and data["stages"]["a"]["status"] == "done"
    assert "duration_sec" in data["stages"]["a"] and data["stages"]["b"]["status"] == "pending"


def test_dead_process_reads_as_interrupted(tmp_path):
    (tmp_path / "status.json").write_text(json.dumps({"state": "running", "pid": 999999999}), encoding="utf-8")
    assert effective_state(read_status(str(tmp_path))) == "interrupted"


def test_bat_files_are_ascii_crlf():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("install.bat", "start.bat"):
        with open(os.path.join(root, name), "rb") as f:
            data = f.read()
        assert all(b < 128 for b in data), f"{name} must be ASCII for cmd.exe on any code page"
        assert data.count(b"\n") == data.count(b"\r\n"), f"{name} must use CRLF line endings"
