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

"""Project task runner (used by the UI; also handy from the command line).

    python po_tasks.py run          --project projects/my_paper [--start_stage sections]
    python po_tasks.py revise       --project ... --instruction "Shorten the abstract" [--section "Abstract"]
    python po_tasks.py regen-figure --project ... --figure_id fig_1 [--instruction ...] [--engine seaborn]
    python po_tasks.py render-code  --project ... --figure_id fig_1
    python po_tasks.py compile      --project ...
    python po_tasks.py export       --project ... --formats pdf,docx,md,latex
    python po_tasks.py review       --project ...
"""

import argparse
import json
import os
import sys
import traceback

os.environ.setdefault("PYTHONUTF8", "1")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

from utils.project_utils import load_project  # noqa: E402
from utils.run_status import STAGES, TASK_STATUS, StatusWriter  # noqa: E402
from utils.settings import ROOT_DIR  # noqa: E402


def project_config(project_dir: str):
    from methods.pipeline import config_from_settings

    meta = load_project(project_dir)
    models = meta.get("models") or {}
    template = meta.get("template", "cvpr2025")
    template_dir = template if os.path.isdir(template) else os.path.join(ROOT_DIR, "templates", template)
    return config_from_settings(
        latex_template_dir=template_dir,
        idea_filename=meta.get("idea_filename", "idea.md"),
        experimental_log_filename=meta.get("experimental_log_filename", "experimental_log.md"),
        writer_model_name=models.get("writer"),
        reflection_model_name=models.get("reflection"),
        plotting_model_name=models.get("plotting"),
        search_model_name=models.get("search"),
        image_model_name=meta.get("image_backend"),
        plot_engine=meta.get("plot_engine"),
        diagram_engine=meta.get("diagram_engine"),
        search_backend=meta.get("search_backend"),
        research_cutoff=meta.get("research_cutoff"),
        use_plotting=bool(meta.get("use_plotting", True)),
        max_reflections=meta.get("max_reflections"),
        plotting_max_critic_rounds=meta.get("plotting_max_critic_rounds"),
    ), meta


def _read_text_arg(value, file_value):
    if file_value:
        with open(file_value, "r", encoding="utf-8") as f:
            return f.read()
    return value


def cmd_run(args):
    from methods.pipeline import run_pipeline

    cfg, _ = project_config(args.project)
    ok = run_pipeline(args.project, cfg, args.start_stage, args.end_stage)
    return 0 if ok else 1


def _task(args, name, func):
    status = StatusWriter(args.project, job=name, stages=[name], filename=TASK_STATUS)
    status.stage(name, "running")
    try:
        result = func(status)
        status.stage(name, "done", message=str(result)[:500] if result else "")
        status.finish("done", result=result if isinstance(result, (dict, list, str)) else None)
        return 0
    except Exception as exc:
        traceback.print_exc()
        status.stage(name, "failed", error=str(exc)[:1000])
        status.finish("failed", error=f"{type(exc).__name__}: {exc}"[:2000])
        return 1


def cmd_revise(args):
    from methods.agents.manual_revision_agent import apply_revision

    instruction = _read_text_arg(args.instruction, args.instruction_file)
    _, meta = project_config(args.project)
    model = args.model or (meta.get("models") or {}).get("revision")

    def go(status):
        status.message(f"Revising {args.section or 'whole paper'} with {model}")
        res = apply_revision(args.project, instruction, args.section, model, compile_pdf=not args.no_compile)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return res

    return _task(args, "revise", go)


def cmd_regen_figure(args):
    from methods.agents.plotting_agent import PlottingAgent
    from methods.pipeline import PipelinePaths, sync_figures

    cfg, _ = project_config(args.project)
    p = PipelinePaths(args.project, cfg)
    instruction = _read_text_arg(args.instruction, args.instruction_file)

    def go(status):
        outline = p.outline_plan if os.path.exists(p.outline_plan) else p.outline
        agent = PlottingAgent(
            model_name=cfg.plotting_model_name,
            image_model_name=args.image_backend or cfg.image_model_name,
            max_critic_rounds=args.critic_rounds if args.critic_rounds is not None else cfg.plotting_max_critic_rounds,
            plot_engine=cfg.plot_engine,
            diagram_engine=cfg.diagram_engine,
        )
        res = agent.run(
            outline_json_path=outline,
            raw_materials_dir=p.materials,
            output_filepath=p.plotting_results,
            figure_ids=[args.figure_id],
            extra_instructions={args.figure_id: instruction} if instruction else None,
            engine_overrides={args.figure_id: args.engine} if args.engine else None,
            reuse_descriptions=args.reuse_description,
        )
        sync_figures(args.project, cfg)
        return f"Regenerated {args.figure_id} ({len(res)} figure records)"

    return _task(args, "regen-figure", go)


def cmd_render_code(args):
    from methods.agents.plotting_agent import figure_slug
    from methods.pipeline import PipelinePaths, sync_figures
    from utils.code_renderers import render_code

    cfg, _ = project_config(args.project)
    p = PipelinePaths(args.project, cfg)

    def go(status):
        with open(p.plotting_results, "r", encoding="utf-8") as f:
            results = json.load(f)
        rec = next((r for r in results if r.get("figure_id") == args.figure_id), None)
        if not rec or not rec.get("code_path"):
            raise ValueError(f"Figure {args.figure_id} has no code to render.")
        code_path = os.path.join(args.project, rec["code_path"])
        with open(code_path, "r", encoding="utf-8") as f:
            code = f.read()
        slug = figure_slug(args.figure_id)
        out = os.path.join(args.project, "figures", f"{slug}.png")
        result = render_code(rec.get("engine", "matplotlib"), code, out, name=slug, aspect_ratio=rec.get("aspect_ratio"))
        if not result.ok:
            raise RuntimeError(result.error)
        rec["image_path"] = f"figures/{slug}.png"
        rec["render_error"] = ""
        if result.animation_path:
            rec["animation_path"] = os.path.relpath(result.animation_path, args.project).replace("\\", "/")
        with open(p.plotting_results, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4, ensure_ascii=False)
        sync_figures(args.project, cfg)
        return f"Rendered {args.figure_id} from {rec['code_path']}"

    return _task(args, "render-code", go)


def cmd_compile(args):
    from methods.agents.manual_revision_agent import compile_final

    def go(status):
        ok, msg = compile_final(args.project)
        if not ok:
            raise RuntimeError(msg)
        return msg

    return _task(args, "compile", go)


def cmd_export(args):
    from utils.export_utils import export_all

    def go(status):
        res = export_all(args.project, [f.strip() for f in args.formats.split(",") if f.strip()])
        print(json.dumps(res, indent=2, ensure_ascii=False))
        failed = {k: v["error"] for k, v in res.items() if not v["ok"]}
        if failed and len(failed) == len(res):
            raise RuntimeError(json.dumps(failed, ensure_ascii=False))
        return res

    return _task(args, "export", go)


def cmd_review(args):
    from autoraters.agent_review import perform_review_agentreview
    from utils.pdf_utils import load_paper

    _, meta = project_config(args.project)
    model = args.model or (meta.get("models") or {}).get("reflection")

    def go(status):
        pdf = os.path.join(args.project, "final_paper.pdf")
        if os.path.exists(pdf):
            text = load_paper(pdf)
        else:
            tex = os.path.join(args.project, "final", "final_paper.tex")
            if not os.path.exists(tex):
                raise FileNotFoundError("Nothing to review yet (no final_paper.pdf or final/final_paper.tex).")
            with open(tex, "r", encoding="utf-8") as f:
                text = f.read()
        review = perform_review_agentreview(text=text, model_name=model)
        out = os.path.join(args.project, "ai_review.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(review, f, indent=2, ensure_ascii=False)
        return {"overall": review.get("Overall") if isinstance(review, dict) else None, "path": out}

    return _task(args, "review", go)


def main():
    parser = argparse.ArgumentParser(description="PaperOrchestra project tasks")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, func):
        sp = sub.add_parser(name)
        sp.add_argument("--project", required=True)
        sp.set_defaults(func=func)
        return sp

    sp = add("run", cmd_run)
    sp.add_argument("--start_stage", default="outline", choices=STAGES)
    sp.add_argument("--end_stage", default="refinement", choices=STAGES)

    sp = add("revise", cmd_revise)
    sp.add_argument("--instruction", default=None)
    sp.add_argument("--instruction_file", default=None)
    sp.add_argument("--section", default=None)
    sp.add_argument("--model", default=None)
    sp.add_argument("--no_compile", action="store_true")

    sp = add("regen-figure", cmd_regen_figure)
    sp.add_argument("--figure_id", required=True)
    sp.add_argument("--instruction", default=None)
    sp.add_argument("--instruction_file", default=None)
    sp.add_argument("--engine", default=None)
    sp.add_argument("--image_backend", default=None)
    sp.add_argument("--critic_rounds", type=int, default=None)
    sp.add_argument("--reuse_description", action="store_true")

    sp = add("render-code", cmd_render_code)
    sp.add_argument("--figure_id", required=True)

    add("compile", cmd_compile)

    sp = add("export", cmd_export)
    sp.add_argument("--formats", default="pdf,docx,md,latex")

    sp = add("review", cmd_review)
    sp.add_argument("--model", default=None)

    args = parser.parse_args()
    args.project = os.path.abspath(args.project)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
