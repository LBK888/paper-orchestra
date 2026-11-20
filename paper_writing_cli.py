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

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

os.environ.setdefault("PYTHONUTF8", "1")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

from utils.run_status import STAGES  # noqa: E402


def str2bool(x):
    return str(x).lower() in ["true", "1", "yes", "y"]


def build_parser():
    parser = argparse.ArgumentParser(
        description="CLI for generating a single paper from the Paper Orchestra pipeline.",
        epilog=(
            "Model names accept a provider prefix: gemini:, openai:, openrouter:, ollama:, "
            "llamacpp:, vllm:, lmstudio:, custom:  (e.g. ollama:qwen3:32b). "
            "Image backends: gemini:<model>, openai:<model>, openrouter:<model>, comfyui[:workflow], "
            "mcp:<server>, http:<api>. Unset options fall back to config/settings.json."
        ),
    )
    parser.add_argument("--raw_materials_dir", default=None,
                        help="Directory containing the raw materials (idea + experimental log). "
                             "Optional when resuming an existing --output_dir.")
    parser.add_argument("--output_dir", default=None,
                        help="Directory to output the generated paper. If not specified, an automatic folder is created.")
    parser.add_argument("--latex_template_dir", default=None,
                        help="Directory containing the LaTeX template (e.g. templates/cvpr2025).")
    parser.add_argument("--idea_filename", default="idea_sparse.md",
                        help="Filename of the idea document within raw_materials. Default: idea_sparse.md")
    parser.add_argument("--experimental_log_filename", default="experimental_log.md",
                        help="Filename of the experimental log within raw_materials. Default: experimental_log.md")
    parser.add_argument("--writer_model_name", default=None, help="LLM for writer and literature agents.")
    parser.add_argument("--reflection_model_name", default=None, help="LLM for reflection agents.")
    parser.add_argument("--search_model_name", default=None, help="LLM used for literature candidate discovery.")
    parser.add_argument("--search_backend", default=None, choices=["auto", "gemini", "semantic_scholar", "llm"],
                        help="Literature discovery backend (default from settings: auto).")
    parser.add_argument("--research_cutoff", default=None,
                        help="Year-Month cutoff date for literature review (e.g., 2024-11). Defaults to current Year-Month.")
    parser.add_argument("--use_plotting", type=str2bool, default=False,
                        help="Enable plotting agent workflow to generate figures.")
    parser.add_argument("--plotting_model_name", default=None, help="LLM for the plotting agent.")
    parser.add_argument("--image_model_name", default=None, help="Image backend for diagrams (see epilog).")
    parser.add_argument("--plot_engine", default=None, choices=["matplotlib", "seaborn", "plotly", "remotion"],
                        help="Engine for data plots.")
    parser.add_argument("--diagram_engine", default=None, choices=["image", "matplotlib", "graphviz", "remotion"],
                        help="Engine for conceptual diagrams ('image' = image-generation backend).")
    parser.add_argument("--plotting_max_critic_rounds", type=int, default=None,
                        help="Maximum rounds of self-correction in the plotting agent.")
    parser.add_argument("--max_reflections", type=int, default=None, help="Content refinement iterations.")
    parser.add_argument("--start_stage", default="outline", choices=STAGES, help="First stage to run.")
    parser.add_argument("--end_stage", default="refinement", choices=STAGES, help="Last stage to run.")
    parser.add_argument("--list_providers", action="store_true", help="Print configured LLM providers and exit.")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.list_providers:
        from utils.settings import load_settings

        settings = load_settings()
        print(json.dumps(
            {
                "providers": {k: {kk: vv for kk, vv in v.items() if kk != "api_key"}
                              for k, v in settings["llm"]["providers"].items()},
                "default_models": settings["llm"]["default_models"],
                "image_default_backend": settings["image"]["default_backend"],
            },
            indent=2,
        ))
        return

    if args.research_cutoff is None:
        args.research_cutoff = datetime.now().strftime("%Y-%m")

    if args.output_dir:
        base_dir = args.output_dir
    else:
        base_dir = f"./paper_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(base_dir, exist_ok=True)

    target_raw_materials = os.path.join(base_dir, "raw_materials")
    if args.raw_materials_dir:
        if not os.path.exists(args.raw_materials_dir):
            print(f"Error: Raw materials directory '{args.raw_materials_dir}' does not exist.")
            sys.exit(1)
        if os.path.abspath(target_raw_materials) != os.path.abspath(args.raw_materials_dir):
            if os.path.exists(target_raw_materials):
                shutil.rmtree(target_raw_materials)
            shutil.copytree(args.raw_materials_dir, target_raw_materials)
    elif not os.path.exists(target_raw_materials):
        print("Error: --raw_materials_dir is required (no raw_materials in the output dir yet).")
        sys.exit(1)

    if not args.latex_template_dir:
        prev_cfg = os.path.join(base_dir, "pipeline_config.json")
        if os.path.exists(prev_cfg):
            with open(prev_cfg, "r", encoding="utf-8") as f:
                args.latex_template_dir = json.load(f).get("latex_template_dir")
    if not args.latex_template_dir or not os.path.isdir(args.latex_template_dir):
        print("Error: --latex_template_dir is required and must exist (e.g. templates/cvpr2025).")
        sys.exit(1)

    if not args.use_plotting:
        figures_dir = os.path.join(target_raw_materials, "figures")
        has_figures = os.path.isdir(figures_dir) and any(
            f.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")) for f in os.listdir(figures_dir)
        )
        if not has_figures:
            print("\n" + "=" * 80)
            print(f"⚠️ WARNING: No figures (.pdf, .png, .jpg) detected in the {figures_dir} directory.")
            print("Since you are running WITHOUT plotting, we are using the provided materials directly.")
            print(f"Please make sure you provide all necessary figures inside {figures_dir}.")
            print("If you don't have figures, run with --use_plotting true to generate them.")
            print("=" * 80 + "\n")

    from methods.pipeline import config_from_settings, run_pipeline

    cfg = config_from_settings(
        latex_template_dir=args.latex_template_dir,
        idea_filename=args.idea_filename,
        experimental_log_filename=args.experimental_log_filename,
        writer_model_name=args.writer_model_name,
        reflection_model_name=args.reflection_model_name,
        plotting_model_name=args.plotting_model_name,
        image_model_name=args.image_model_name,
        search_model_name=args.search_model_name,
        search_backend=args.search_backend,
        research_cutoff=args.research_cutoff,
        use_plotting=args.use_plotting,
        plotting_max_critic_rounds=args.plotting_max_critic_rounds,
        plot_engine=args.plot_engine,
        diagram_engine=args.diagram_engine,
        max_reflections=args.max_reflections,
    )
    mode = "WITH PLOTTING" if args.use_plotting else "WITHOUT PLOTTING"
    print(f"🚀 Starting Paper Generation ({mode}) in {base_dir}")
    print(f"   writer={cfg.writer_model_name} reflection={cfg.reflection_model_name} "
          f"plotting={cfg.plotting_model_name} image={cfg.image_model_name}")
    ok = run_pipeline(base_dir, cfg, start_stage=args.start_stage, end_stage=args.end_stage)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
