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

"""Staged, resumable paper-writing pipeline.

Stages: outline -> literature (+ figures in parallel) -> sections -> refinement.
Every stage reads its inputs from disk, so a run can start from any stage
(e.g. after editing ``outline_plan.json`` or replacing a figure in the UI).
Progress is written to ``<base_dir>/status.json``.
"""

import json
import os
import os.path as osp
import shutil
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from utils.pdf_utils import latex_available
from utils.run_status import STAGES, StatusWriter
from utils.settings import get_setting

IMAGE_EXTS = (".pdf", ".png", ".jpg", ".jpeg")


@dataclass
class PipelineConfig:
    latex_template_dir: str
    idea_filename: str = "idea_sparse.md"
    experimental_log_filename: str = "experimental_log.md"
    writer_model_name: str = "gemini-3.1-pro-preview"
    reflection_model_name: str = "gemini-3.1-pro-preview"
    plotting_model_name: str = "gemini-3.1-pro-preview"
    image_model_name: str = "gemini-3-pro-image-preview"
    search_model_name: Optional[str] = None
    search_backend: Optional[str] = None
    research_cutoff: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m"))
    use_plotting: bool = True
    plotting_max_critic_rounds: int = 3
    plot_engine: Optional[str] = None
    diagram_engine: Optional[str] = None
    max_reflections: int = 3
    lit_max_workers: int = 3
    max_retries: int = 3


class PipelinePaths:
    def __init__(self, base_dir: str, cfg: PipelineConfig):
        self.base = base_dir
        self.materials = osp.join(base_dir, "raw_materials")
        self.latex = osp.join(base_dir, "latex_writeup")
        self.latex_figures = osp.join(self.latex, "figures")
        self.guidelines = osp.join(self.latex, "guidelines.md")
        self.template = osp.join(self.latex, "template.tex")
        self.idea = osp.join(self.materials, cfg.idea_filename)
        self.exp_log = osp.join(self.materials, cfg.experimental_log_filename)
        self.outline = osp.join(base_dir, "outline.json")
        self.outline_plan = osp.join(base_dir, "outline_plan.json")
        self.lit_out = osp.join(base_dir, "literature_agent_output")
        self.citation_map = osp.join(self.lit_out, "citation_map.json")
        self.plotting_results = osp.join(base_dir, "plotting_results.json")
        self.raw_draft = osp.join(self.latex, "raw_draft_paper.tex")
        self.refine_dir = osp.join(base_dir, "content_refinement_workdir")
        self.final_dir = osp.join(base_dir, "final")
        self.final_tex = osp.join(self.final_dir, "final_paper.tex")
        self.final_pdf = osp.join(base_dir, "final_paper.pdf")
        self.time_log = osp.join(base_dir, "time_breakdown.json")


def _require(path: str, hint: str):
    if not osp.exists(path):
        raise FileNotFoundError(f"Missing '{path}'. {hint}")


def stage_range(start_stage: str = "outline", end_stage: str = "refinement") -> List[str]:
    if start_stage not in STAGES or end_stage not in STAGES:
        raise ValueError(f"Stages must be one of {STAGES}")
    i, j = STAGES.index(start_stage), STAGES.index(end_stage)
    if i > j:
        raise ValueError(f"start_stage '{start_stage}' comes after end_stage '{end_stage}'")
    return STAGES[i : j + 1]


# ---------------------------------------------------------------------------
# stage implementations
# ---------------------------------------------------------------------------


def _prepare_latex_dir(p: PipelinePaths, cfg: PipelineConfig, fresh: bool):
    if fresh and osp.exists(p.latex):
        shutil.rmtree(p.latex)
    os.makedirs(p.latex_figures, exist_ok=True)
    shutil.copytree(cfg.latex_template_dir, p.latex, dirs_exist_ok=True)


def run_outline(p: PipelinePaths, cfg: PipelineConfig):
    from methods.agents.outline_agent import OutlineAgent

    _prepare_latex_dir(p, cfg, fresh=True)
    for path, hint in (
        (p.guidelines, "The LaTeX template folder needs a guidelines.md."),
        (p.template, "The LaTeX template folder needs a template.tex."),
        (p.idea, "Provide the idea file in raw_materials."),
        (p.exp_log, "Provide the experimental log in raw_materials."),
    ):
        _require(path, hint)
    OutlineAgent(model_name=cfg.writer_model_name, cutoff_date=cfg.research_cutoff).run(
        idea_file=p.idea,
        experimental_log_file=p.exp_log,
        latex_template_file=p.template,
        conference_guidelines_file=p.guidelines,
        output_filepath=p.outline,
    )
    shutil.copy(p.outline, p.outline_plan)


def _plan_path(p: PipelinePaths) -> str:
    return p.outline_plan if osp.exists(p.outline_plan) else p.outline


def run_literature(p: PipelinePaths, cfg: PipelineConfig):
    from methods.agents.literature_review_agent import HybridLiteratureAgent

    _require(_plan_path(p), "Run the outline stage first.")
    if not osp.exists(p.template):
        _prepare_latex_dir(p, cfg, fresh=False)
    # Always start from the pristine template (the stage rewrites template.tex).
    shutil.copy(osp.join(cfg.latex_template_dir, "template.tex"), p.template)
    plan_copy = osp.join(p.base, "outline_for_literature.json")
    shutil.copy(_plan_path(p), plan_copy)

    agent = HybridLiteratureAgent(
        idea_path=p.idea,
        experimental_log_path=p.exp_log,
        latex_template_path=p.template,
        conference_guidelines_path=p.guidelines,
        output_dir=p.lit_out,
        model_name=cfg.writer_model_name,
        max_workers=cfg.lit_max_workers,
        search_model_name=cfg.search_model_name,
        search_backend=cfg.search_backend,
    )
    agent.run(outline_path=plan_copy, cutoff_date=cfg.research_cutoff)
    shutil.copy(osp.join(p.lit_out, "outline_v1.json"), p.outline)
    shutil.copy(osp.join(p.lit_out, "updated_template.tex"), p.template)
    shutil.copy(osp.join(p.lit_out, "references.bib"), osp.join(p.latex, "references.bib"))


def run_figures(p: PipelinePaths, cfg: PipelineConfig):
    if cfg.use_plotting:
        from methods.agents.plotting_agent import PlottingAgent

        _require(_plan_path(p), "Run the outline stage first.")
        PlottingAgent(
            model_name=cfg.plotting_model_name,
            image_model_name=cfg.image_model_name,
            max_critic_rounds=cfg.plotting_max_critic_rounds,
            plot_engine=cfg.plot_engine,
            diagram_engine=cfg.diagram_engine,
        ).run(
            outline_json_path=_plan_path(p),
            raw_materials_dir=p.materials,
            output_filepath=p.plotting_results,
        )
    sync_figures(p.base, cfg)


def sync_figures(base_dir: str, cfg: PipelineConfig) -> List[Dict]:
    """Rebuilds latex_writeup/figures (+ info.json) from user-provided figures
    (raw_materials/figures) and generated figures (plotting_results.json)."""
    p = PipelinePaths(base_dir, cfg)
    os.makedirs(p.latex_figures, exist_ok=True)
    info: List[Dict] = []
    seen = set()

    provided_dir = osp.join(p.materials, "figures")
    provided_info = {}
    if osp.exists(osp.join(provided_dir, "info.json")):
        with open(osp.join(provided_dir, "info.json"), "r", encoding="utf-8") as f:
            for item in json.load(f):
                provided_info[item.get("name")] = item.get("caption", "")
    if osp.isdir(provided_dir):
        for name in sorted(os.listdir(provided_dir)):
            if name.lower().endswith(IMAGE_EXTS):
                shutil.copy(osp.join(provided_dir, name), osp.join(p.latex_figures, name))
                info.append({"name": name, "caption": provided_info.get(name, ""), "source": "provided"})
                seen.add(name)

    if cfg.use_plotting and osp.exists(p.plotting_results):
        with open(p.plotting_results, "r", encoding="utf-8") as f:
            results = json.load(f)
        for res in results:
            rel = res.get("image_path")
            if not rel or res.get("excluded"):
                continue
            src = osp.join(base_dir, rel)
            if not osp.exists(src):
                continue
            name = osp.basename(src)
            if name in seen:
                continue
            shutil.copy(src, osp.join(p.latex_figures, name))
            info.append({"name": name, "caption": res.get("caption", ""), "source": "generated"})
            seen.add(name)

    with open(osp.join(p.latex_figures, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=4, ensure_ascii=False)
    return info


def run_sections(p: PipelinePaths, cfg: PipelineConfig):
    from methods.agents.section_writing_agent import SectionWritingAgent

    _require(p.outline, "Run the outline/literature stages first.")
    _require(p.citation_map, "Run the literature stage first.")
    sync_figures(p.base, cfg)
    SectionWritingAgent(
        outline_path=p.outline,
        template_path=p.template,
        idea_path=p.idea,
        experimental_log_path=p.exp_log,
        citation_map_path=p.citation_map,
        figures_info_path=osp.join(p.latex_figures, "info.json"),
        guidelines_path=p.guidelines,
        model_name=cfg.writer_model_name,
    ).run(output_path=p.raw_draft)
    _require(p.raw_draft, "Section writing produced no LaTeX.")


def finalize_from_tex(p: PipelinePaths, tex_path: str, pdf_path: Optional[str] = None):
    """Creates <base>/final/: a self-contained, compilable LaTeX folder."""
    if osp.exists(p.final_dir):
        shutil.rmtree(p.final_dir)
    shutil.copytree(
        p.latex,
        p.final_dir,
        ignore=shutil.ignore_patterns("*.aux", "*.log", "*.out", "*.blg", "*.bbl", "raw_draft_paper.*"),
    )
    shutil.copy(tex_path, p.final_tex)
    if pdf_path and osp.exists(pdf_path):
        shutil.copy(pdf_path, osp.join(p.final_dir, "final_paper.pdf"))
        shutil.copy(pdf_path, p.final_pdf)


def run_refinement(p: PipelinePaths, cfg: PipelineConfig, status: StatusWriter):
    from methods.agents.content_refinement_agent import ContentRefinementAgent

    _require(p.raw_draft, "Run the section-writing stage first.")
    if not latex_available():
        msg = (
            "pdflatex/bibtex not found: skipped review-and-refine and PDF compilation. "
            "The raw draft was finalized; install MiKTeX or TeX Live and re-run this stage for a PDF."
        )
        print(f"⚠️ {msg}")
        finalize_from_tex(p, p.raw_draft)
        return "skipped", msg

    if osp.exists(p.refine_dir):
        shutil.rmtree(p.refine_dir)
    shutil.copytree(p.latex, p.refine_dir, dirs_exist_ok=True)
    pdf = ContentRefinementAgent(
        experimental_log_path=p.exp_log,
        citation_map_path=p.citation_map,
        guidelines_path=p.guidelines,
        model_name=cfg.reflection_model_name,
        max_reflections=cfg.max_reflections,
        work_dir=p.refine_dir,
    ).run(texfile_path=p.raw_draft)
    if not pdf or not osp.exists(pdf):
        raise RuntimeError(f"Content refinement produced no PDF ({pdf}).")
    final_tex = osp.join(p.refine_dir, "final_refined_paper.tex")
    finalize_from_tex(p, final_tex, pdf)
    print(" >> Final PDF saved to:\n", p.final_pdf)
    return "done", ""


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def _with_retries(name: str, func, max_retries: int):
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception:
            print(f"[{name}] attempt {attempt}/{max_retries} failed:")
            print(traceback.format_exc())
            if attempt == max_retries:
                raise
            print(f"[{name}] retrying...")


def run_pipeline(
    base_dir: str,
    cfg: PipelineConfig,
    start_stage: str = "outline",
    end_stage: str = "refinement",
) -> bool:
    stages = stage_range(start_stage, end_stage)
    p = PipelinePaths(base_dir, cfg)
    status = StatusWriter(base_dir, job="pipeline")
    for s in stages:
        status.stage(s, "pending")
    with open(osp.join(base_dir, "pipeline_config.json"), "w", encoding="utf-8") as f:
        json.dump({**asdict(cfg), "stages": stages}, f, indent=4, ensure_ascii=False)

    time_log = {}
    if osp.exists(p.time_log):
        with open(p.time_log, "r", encoding="utf-8") as f:
            time_log = json.load(f)
    t_start = time.time()
    _require(p.materials, "Raw materials folder is missing.")
    print(f"🚀 Pipeline stages: {' -> '.join(stages)}  (base dir: {base_dir})")

    try:
        if "outline" in stages:
            status.stage("outline", "running")
            t0 = time.time()
            _with_retries("outline", lambda: run_outline(p, cfg), cfg.max_retries)
            time_log["OutlineAgent"] = time.time() - t0
            status.stage("outline", "done")

        parallel = [s for s in ("literature", "figures") if s in stages]
        if parallel:
            t1 = time.time()
            jobs = {
                "literature": lambda: run_literature(p, cfg),
                "figures": lambda: run_figures(p, cfg),
            }
            errors = {}
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {}
                for s in parallel:
                    status.stage(s, "running")
                    futures[s] = pool.submit(_with_retries, s, jobs[s], cfg.max_retries)
                for s, fut in futures.items():
                    try:
                        fut.result()
                        status.stage(s, "done")
                    except Exception as exc:
                        errors[s] = exc
                        status.stage(s, "failed", error=str(exc)[:1000])
            time_log["Parallel_Lit_and_Plot"] = time.time() - t1
            if errors:
                raise RuntimeError(f"Stage(s) failed: {', '.join(errors)}") from next(iter(errors.values()))

        if "sections" in stages:
            status.stage("sections", "running")
            t2 = time.time()
            _with_retries("sections", lambda: run_sections(p, cfg), cfg.max_retries)
            time_log["SectionWritingAgent"] = time.time() - t2
            status.stage("sections", "done")
            if end_stage == "sections":
                finalize_from_tex(p, p.raw_draft)

        if "refinement" in stages:
            status.stage("refinement", "running")
            t3 = time.time()
            outcome, msg = _with_retries(
                "refinement", lambda: run_refinement(p, cfg, status), cfg.max_retries
            )
            time_log["ContentRefinementAgent"] = time.time() - t3
            status.stage("refinement", outcome, message=msg)

        time_log["Total_Time_Span"] = time.time() - t_start
        with open(p.time_log, "w", encoding="utf-8") as f:
            json.dump(time_log, f, indent=4)
        status.finish("done")
        print("✅ Pipeline finished.")
        return True
    except Exception as exc:
        current = status.data.get("current_stage")
        if current and status.data["stages"].get(current, {}).get("status") == "running":
            status.stage(current, "failed", error=str(exc)[:1000])
        status.finish("failed", error=f"{type(exc).__name__}: {exc}"[:2000])
        print(f"❌ Pipeline failed: {exc}")
        return False


def config_from_settings(**overrides) -> PipelineConfig:
    """Builds a PipelineConfig using Settings defaults, then explicit overrides."""
    models = get_setting("llm.default_models", {}) or {}
    defaults = dict(
        writer_model_name=models.get("writer", "gemini-3.1-pro-preview"),
        reflection_model_name=models.get("reflection", "gemini-3.1-pro-preview"),
        plotting_model_name=models.get("plotting", "gemini-3.1-pro-preview"),
        image_model_name=get_setting("image.default_backend", "gemini-3-pro-image-preview"),
        search_model_name=models.get("search"),
        search_backend=get_setting("literature.search_backend", "auto"),
        plot_engine=get_setting("plotting.plot_engine", "matplotlib"),
        diagram_engine=get_setting("plotting.diagram_engine", "image"),
        max_reflections=int(get_setting("pipeline.max_reflections", 3)),
        plotting_max_critic_rounds=int(get_setting("pipeline.plotting_max_critic_rounds", 3)),
        max_retries=int(get_setting("pipeline.max_pipeline_retries", 3)),
    )
    defaults.update({k: v for k, v in overrides.items() if v is not None})
    return PipelineConfig(**defaults)
