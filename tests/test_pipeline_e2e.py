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

"""End-to-end: staged pipeline on a project, then every po_tasks.py command.

The real agents run against the mock LLM; Semantic Scholar is stubbed so the
test is offline and deterministic. Tests in this module share one project and
run in file order.
"""

import json
import os
import subprocess
import sys

import pytest

from tests.mock_backend import ROOT

pytestmark = pytest.mark.slow

S2_PAPERS = [
    {"title": "Attention Is All You Need", "authors": [{"name": "Ashish Vaswani"}], "venue": "NeurIPS",
     "year": 2017, "abstract": "The dominant sequence transduction models...", "citationCount": 100000,
     "publicationDate": "2017-06-12", "journal": None},
    {"title": "Transformers are RNNs: Fast Autoregressive Transformers with Linear Attention",
     "authors": [{"name": "Angelos Katharopoulos"}], "venue": "ICML", "year": 2020,
     "abstract": "Transformers achieve remarkable performance...", "citationCount": 1500,
     "publicationDate": "2020-06-29", "journal": None},
]


def _read_json(project, rel):
    with open(os.path.join(project, rel), "r", encoding="utf-8") as f:
        return json.load(f)


def _task(project, *args):
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "po_tasks.py"), *args, "--project", project],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    return proc.returncode, proc.stdout + proc.stderr


@pytest.fixture(scope="module")
def project(mock_backend):
    import methods.agents.literature_review_agent as lit
    from utils.project_utils import create_project, load_project, save_project

    mp = pytest.MonkeyPatch()
    mp.setattr(lit, "s2_keyword_search", lambda q, limit=20, cutoff_date=None: S2_PAPERS)
    mp.setattr(
        lit, "s2_title_search",
        lambda title, year=None, cutoff=None: next(
            (p for p in S2_PAPERS if p["title"].lower() == str(title).lower()), S2_PAPERS[0]
        ),
    )
    path = create_project("E2E 測試 paper")  # non-ASCII name on purpose (Windows code pages)
    raw = os.path.join(path, "raw_materials")
    with open(os.path.join(raw, "idea.md"), "w", encoding="utf-8") as f:
        f.write("# Idea\nLinear attention for long sequences. 中文說明。")
    with open(os.path.join(raw, "experimental_log.md"), "w", encoding="utf-8") as f:
        f.write("| method | acc |\n|A|71.2|\n|B|75.9|\n|Ours|80.3|")
    meta = load_project(path)
    meta.update({
        "template": "cvpr2025", "use_plotting": True, "plot_engine": "matplotlib",
        "diagram_engine": "matplotlib", "search_backend": "semantic_scholar",
        "image_backend": "comfyui", "plotting_max_critic_rounds": 1,
    })
    save_project(path, meta)
    yield path
    mp.undo()


def test_full_pipeline(project, monkeypatch):
    from methods.pipeline import run_pipeline
    from po_tasks import project_config
    from utils.pdf_utils import latex_available
    from utils.run_status import read_status

    cfg, _ = project_config(project)
    assert run_pipeline(project, cfg)

    status = read_status(project)
    assert status["state"] == "done"
    stages = {k: v["status"] for k, v in status["stages"].items()}
    # Without pdflatex/bibtex the refine-and-compile stage is skipped on purpose.
    refinement = "done" if latex_available() else "skipped"
    assert stages == {"outline": "done", "literature": "done", "figures": "done",
                      "sections": "done", "refinement": refinement}
    if latex_available():
        assert os.path.getsize(os.path.join(project, "final_paper.pdf")) > 1000

    for rel in ["outline.json", "outline_plan.json", "literature_agent_output/citation_map.json",
                "latex_writeup/references.bib", "plotting_results.json", "figures/fig_results_bar.png",
                "figures/fig_method_overview.png", "figures/src/fig_results_bar.py",
                "latex_writeup/figures/info.json", "latex_writeup/raw_draft_paper.tex",
                "final/final_paper.tex", "time_breakdown.json"]:
        assert os.path.exists(os.path.join(project, rel)), rel

    figures = _read_json(project, "plotting_results.json")
    assert {r["figure_id"]: r["engine"] for r in figures} == {
        "fig_results_bar": "matplotlib", "fig_method_overview": "matplotlib"}
    assert set(_read_json(project, "literature_agent_output/citation_map.json")) == {
        "Vaswani2017AttentionAll", "Katharopoulos2020TransformersRnns"}
    assert len(_read_json(project, "latex_writeup/figures/info.json")) == 2


def test_resume_single_stage_keeps_earlier_stages(project):
    from methods.pipeline import run_pipeline
    from po_tasks import project_config
    from utils.run_status import read_status

    cfg, _ = project_config(project)
    assert run_pipeline(project, cfg, start_stage="sections", end_stage="sections")
    stages = read_status(project)["stages"]
    assert stages["outline"]["status"] == "done" and stages["sections"]["status"] == "done"


def test_task_revise_one_section(project):
    rc, out = _task(project, "revise", "--instruction", "Make the abstract stronger", "--section", "Abstract")
    assert rc == 0, out[-1500:]
    with open(os.path.join(project, "final", "final_paper.tex"), encoding="utf-8") as f:
        tex = f.read()
    assert "very efficient (revised)" in tex  # abstract changed
    assert "Our method uses" in tex           # rest of the paper untouched
    meta = _read_json(project, "revisions/rev_001/meta.json")
    assert meta["section"] == "Abstract" and meta["summary"] == "strengthened"
    task = _read_json(project, "task_status.json")
    assert task["job"] == "revise" and task["state"] == "done"


def test_revert_restores_previous_text(project):
    from methods.agents.manual_revision_agent import list_revisions, revert_to

    rev = list_revisions(project)[0]["id"]
    revert_to(project, rev, "before")
    with open(os.path.join(project, "final", "final_paper.tex"), encoding="utf-8") as f:
        assert "very efficient (revised)" not in f.read()
    assert len(list_revisions(project)) == 2  # the revert itself is recorded


def test_task_regenerate_figure_with_engine_override(project):
    rc, out = _task(project, "regen-figure", "--figure_id", "fig_results_bar", "--engine", "seaborn",
                    "--instruction", "Use horizontal bars", "--critic_rounds", "0", "--reuse_description")
    assert rc == 0, out[-1500:]
    figures = {r["figure_id"]: r for r in _read_json(project, "plotting_results.json")}
    assert len(figures) == 2  # merged, not replaced
    assert figures["fig_results_bar"]["engine"] == "seaborn"


def test_task_render_edited_code(project):
    rec = {r["figure_id"]: r for r in _read_json(project, "plotting_results.json")}["fig_results_bar"]
    code_path = os.path.join(project, rec["code_path"])
    with open(code_path, encoding="utf-8") as f:
        code = f.read()
    with open(code_path, "w", encoding="utf-8") as f:
        f.write(code.replace("ax.bar(", "ax.barh("))
    before = os.path.getmtime(os.path.join(project, "figures", "fig_results_bar.png"))
    rc, out = _task(project, "render-code", "--figure_id", "fig_results_bar")
    assert rc == 0, out[-1500:]
    assert os.path.getmtime(os.path.join(project, "figures", "fig_results_bar.png")) > before


def test_task_export(project):
    from utils.export_utils import pandoc_path

    rc, out = _task(project, "export", "--formats", "docx,md,latex")
    assert rc == 0, out[-1500:]
    assert os.path.exists(os.path.join(project, "exports", "paper_latex.zip"))
    if pandoc_path():
        assert os.path.exists(os.path.join(project, "exports", "paper.docx"))
        with open(os.path.join(project, "exports", "paper.md"), encoding="utf-8") as f:
            md = f.read()
        assert "# Introduction" in md and "paper_media/" in md


def test_task_ai_review(project):
    rc, out = _task(project, "review")
    assert rc == 0, out[-1500:]
    assert _read_json(project, "ai_review.json")["Overall"] == 6


def test_project_zip_roundtrip(project):
    from utils.project_utils import export_project_zip, import_project_zip, list_projects

    restored = import_project_zip(export_project_zip(project))
    assert restored != project
    assert os.path.exists(os.path.join(restored, "final", "final_paper.tex"))
    assert os.path.exists(os.path.join(restored, "project.json"))
    assert {p["path"] for p in list_projects()} >= {project, restored}
