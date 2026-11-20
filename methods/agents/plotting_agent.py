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

import os
import json
import base64
import shutil
import traceback
import concurrent.futures
from typing import Dict, List, Optional

from utils.common_utils import load_md_file
from utils.paper_banana_utils import (
    retrieve_few_shot_examples,
    predict_figure_content,
    style_figure_content,
    generate_figure_with_engine,
    critique_and_revise_figure,
    generate_figure_caption,
)


def figure_slug(figure_id: str) -> str:
    return (figure_id or "figure").replace(" ", "_").lower()


def _task_name(plot_type: str) -> str:
    plot_type = (plot_type or "").lower()
    if plot_type in ["plot", "diagram"]:
        return plot_type
    return "plot" if "chart" in plot_type or "plot" in plot_type else "diagram"


def gather_raw_content(raw_materials_dir: str, data_source_str: str) -> str:
    raw_content = ""
    data_source_str = (data_source_str or "").lower()
    for filename in sorted(os.listdir(raw_materials_dir)):
        if not filename.endswith(".md"):
            continue
        filename_lower = filename.lower()
        match = ("idea" in data_source_str and "idea" in filename_lower) or (
            "experiment" in data_source_str and "experiment" in filename_lower
        )
        if match or filename_lower in data_source_str:
            raw_content += f"\n--- {filename} ---\n"
            raw_content += load_md_file(os.path.join(raw_materials_dir, filename)) or ""

    if not raw_content:
        for filename in ["experimental_log.md", "idea_sparse.md", "idea_dense.md", "idea.md"]:
            filepath = os.path.join(raw_materials_dir, filename)
            if os.path.exists(filepath):
                raw_content += f"\n--- {filename} ---\n"
                raw_content += load_md_file(filepath) or ""
    return raw_content


def process_single_figure(
    fig_plan,
    raw_materials_dir,
    model_name="gemini-3.1-pro-preview",
    image_model_name="gemini-3-pro-image-preview",
    max_critic_rounds=3,
    engine: Optional[str] = None,
    work_dir: Optional[str] = None,
    extra_instruction: Optional[str] = None,
    skip_planning_description: Optional[str] = None,
):
    fig_id = fig_plan.get("figure_id", "Unknown")
    print(f"Processing figure: {fig_id}")
    title = fig_plan.get("title", "")
    objective = fig_plan.get("objective", "")
    aspect_ratio = fig_plan.get("aspect_ratio", "16:9")
    task_name = _task_name(fig_plan.get("plot_type", ""))
    engine = fig_plan.get("engine") or engine

    raw_content = gather_raw_content(raw_materials_dir, fig_plan.get("data_source", ""))
    visual_intent = f"Title: {title}\nObjective: {objective}"
    if extra_instruction:
        visual_intent += f"\nAdditional author instructions (must be followed): {extra_instruction}"

    if skip_planning_description:
        styled_figure_desc = skip_planning_description
        if extra_instruction:
            styled_figure_desc += f"\n\nRevision requested by the author: {extra_instruction}"
    else:
        # 1. Retrieve few-shot examples
        print(f"[{fig_id}] Retrieving few-shot examples...")
        examples = retrieve_few_shot_examples(
            task_name=task_name,
            raw_content=raw_content,
            description=visual_intent,
            model_name=model_name,
        )

        # 2. Plan/Predict Content
        print(f"[{fig_id}] Planning figure content...")
        figure_desc = predict_figure_content(
            task_name=task_name,
            raw_content=raw_content,
            description=visual_intent,
            examples=examples,
            model_name=model_name,
        )

        # 3. Stylist Refinement
        print(f"[{fig_id}] Styling figure content...")
        styled_figure_desc = style_figure_content(
            task_name=task_name,
            raw_content=raw_content,
            description=visual_intent,
            figure_desc=figure_desc,
            model_name=model_name,
        )

    # 4. Initial Generation
    print(f"[{fig_id}] Generating initial visual (aspect ratio {aspect_ratio}, engine {engine or 'default'})...")
    gen = generate_figure_with_engine(
        task_name=task_name,
        figure_description=styled_figure_desc,
        model_name=model_name,
        image_model_name=image_model_name,
        aspect_ratio=aspect_ratio,
        engine=engine,
        work_dir=work_dir,
        figure_id=figure_slug(fig_id),
    )
    print(f"[{fig_id}] Engine used: {gen['engine']}")

    current_description = styled_figure_desc
    current_gen = gen

    # 5. Critic Iteration
    critic_history = []
    for round_idx in range(max_critic_rounds):
        print(f"[{fig_id}] Running critic round {round_idx + 1}/{max_critic_rounds}...")
        try:
            revised_desc, suggestions = critique_and_revise_figure(
                task_name=task_name,
                raw_content=raw_content,
                description=visual_intent,
                figure_desc=current_description,
                base64_image=current_gen["base64_img"],
                round_idx=round_idx,
                model_name=model_name,
            )

            critic_history.append(
                {
                    "round": round_idx,
                    "suggestions": suggestions,
                    "revised_description": revised_desc,
                }
            )

            if suggestions.strip() == "No changes needed.":
                print(f"[{fig_id}] Critic round {round_idx + 1}: No changes needed. Finishing refinement.")
                break

            print(f"[{fig_id}] Critic round {round_idx + 1}: Changes needed. Re-generating...")
            current_description = revised_desc
            new_gen = generate_figure_with_engine(
                task_name=task_name,
                figure_description=current_description,
                model_name=model_name,
                image_model_name=image_model_name,
                aspect_ratio=aspect_ratio,
                engine=gen["engine"],
                work_dir=work_dir,
                figure_id=figure_slug(fig_id),
            )
            if new_gen["base64_img"]:
                current_gen = new_gen
        except Exception as e:
            print(f"[ERROR in {fig_id} Critic Round {round_idx + 1}]: {e}")
            break

    print(f"[{fig_id}] Generating caption...")
    caption = generate_figure_caption(
        task_name=task_name,
        raw_content=raw_content,
        description=visual_intent,
        figure_desc=current_description,
        base64_image=current_gen["base64_img"],
        model_name=model_name,
    )

    clean_description = current_description
    for marker in ("**Detailed Description:**", "Detailed Description:"):
        clean_description = clean_description.replace(marker, "").strip()

    print(f"[{fig_id}] Figure processing complete.")
    return {
        "figure_id": fig_plan.get("figure_id"),
        "title": title,
        "task_name": task_name,
        "engine": current_gen["engine"],
        "description": clean_description,
        "caption": caption,
        "aspect_ratio": aspect_ratio,
        "critic_history": critic_history,
        "code_path": current_gen.get("code_path"),
        "animation_path": current_gen.get("animation_path"),
        "render_error": current_gen.get("error", ""),
        "base64_img": current_gen["base64_img"],
    }


def save_figure_results(results: List[Dict], output_filepath: str, merge_existing: bool = False) -> List[Dict]:
    """Writes images as PNG to <dir>/figures/ and the JSON summary to ``output_filepath``."""
    output_dir = os.path.dirname(os.path.abspath(output_filepath))
    figures_dir = os.path.join(output_dir, "figures")
    src_dir = os.path.join(figures_dir, "src")
    os.makedirs(src_dir, exist_ok=True)

    for res in results:
        slug = figure_slug(res.get("figure_id"))
        if res.get("base64_img"):
            img_path = os.path.join(figures_dir, f"{slug}.png")
            try:
                with open(img_path, "wb") as fh:
                    fh.write(base64.b64decode(res["base64_img"]))
                print(f"Saved {img_path}")
                res["image_path"] = f"figures/{slug}.png"
            except Exception as e:
                print(f"Failed to save image {slug}: {e}")
        for key, sub in (("code_path", "src"), ("animation_path", "")):
            path = res.get(key)
            if path and os.path.exists(path):
                dst_dir = os.path.join(figures_dir, sub) if sub else figures_dir
                dst = os.path.join(dst_dir, os.path.basename(path))
                if os.path.abspath(path) != os.path.abspath(dst):
                    shutil.copy(path, dst)
                res[key] = os.path.relpath(dst, output_dir).replace("\\", "/")
        res.pop("base64_img", None)

    if merge_existing and os.path.exists(output_filepath):
        with open(output_filepath, "r", encoding="utf-8") as f:
            existing = json.load(f)
        by_id = {r.get("figure_id"): r for r in existing}
        for res in results:
            by_id[res.get("figure_id")] = res
        results = list(by_id.values())

    with open(output_filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)
    return results


class PlottingAgent:
    def __init__(
        self,
        model_name: str = "gemini-3.1-pro-preview",
        image_model_name: str = "gemini-3-pro-image-preview",
        max_critic_rounds: int = 3,
        plot_engine: Optional[str] = None,
        diagram_engine: Optional[str] = None,
        max_workers: int = 5,
    ):
        self.model_name = model_name
        self.image_model_name = image_model_name
        self.max_critic_rounds = max_critic_rounds
        self.plot_engine = plot_engine
        self.diagram_engine = diagram_engine
        self.max_workers = max_workers

    def _engine_for(self, plan: Dict) -> Optional[str]:
        if plan.get("engine"):
            return plan["engine"]
        return self.plot_engine if _task_name(plan.get("plot_type", "")) == "plot" else self.diagram_engine

    def run(
        self,
        outline_json_path: str,
        raw_materials_dir: str,
        output_filepath: str = None,
        figure_ids: Optional[List[str]] = None,
        extra_instructions: Optional[Dict[str, str]] = None,
        engine_overrides: Optional[Dict[str, str]] = None,
        reuse_descriptions: bool = False,
    ):
        with open(outline_json_path, "r", encoding="utf-8") as f:
            outline_data = json.load(f)

        plotting_plan = outline_data.get("plotting_plan", [])
        if figure_ids:
            plotting_plan = [p for p in plotting_plan if p.get("figure_id") in figure_ids]
        extra_instructions = extra_instructions or {}
        engine_overrides = engine_overrides or {}

        previous = {}
        if reuse_descriptions and output_filepath and os.path.exists(output_filepath):
            with open(output_filepath, "r", encoding="utf-8") as f:
                previous = {r.get("figure_id"): r for r in json.load(f)}

        work_root = os.path.join(os.path.dirname(os.path.abspath(output_filepath or outline_json_path)), "figures", "work")
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for plan in plotting_plan:
                fid = plan.get("figure_id")
                futures[
                    executor.submit(
                        process_single_figure,
                        plan,
                        raw_materials_dir,
                        self.model_name,
                        self.image_model_name,
                        self.max_critic_rounds,
                        engine_overrides.get(fid) or self._engine_for(plan),
                        os.path.join(work_root, figure_slug(fid)),
                        extra_instructions.get(fid),
                        (previous.get(fid) or {}).get("description") if reuse_descriptions else None,
                    )
                ] = plan
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    plan = futures[future]
                    print(f"[ERROR] Failed processing {plan.get('figure_id')}: {e}")
                    traceback.print_exc()

        if output_filepath:
            results = save_figure_results(results, output_filepath, merge_existing=bool(figure_ids))
        return results
