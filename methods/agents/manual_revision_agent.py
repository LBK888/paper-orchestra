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

"""Human-in-the-loop revision: apply an author's instruction to the paper
(whole paper or one section), keep a revision history, and recompile."""

import difflib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from utils.llm_backend_utils import call_llm_with_contents
from utils.pdf_utils import compile_latex, latex_available
from utils.prompt_utils import UNIVERSAL_NO_LEAKAGE_PROMPT
from utils.settings import get_setting

SECTION_RE = re.compile(r"\\section\*?\{((?:[^{}]|\{[^{}]*\})*)\}")
END_MARKERS = (r"\bibliographystyle", r"\bibliography{", r"\end{document}", r"\appendix")

REVISION_SYSTEM_PROMPT = (
    "You are an expert academic editor revising a LaTeX research paper exactly as the author asks.\n"
    "Rules:\n"
    "- Apply the author's instruction faithfully; do not make unrelated changes.\n"
    "- Keep LaTeX valid: balanced environments, existing labels, \\cite keys and \\ref targets.\n"
    "- Never invent experimental numbers or citations that are not in the provided materials.\n"
    "- Keep the paper anonymous.\n"
    + UNIVERSAL_NO_LEAKAGE_PROMPT
)


@dataclass
class Section:
    title: str
    start: int
    end: int


def list_sections(tex: str) -> List[Section]:
    """Top-level parts of a paper: Abstract plus each \\section."""
    sections: List[Section] = []
    m = re.search(r"\\begin\{abstract\}.*?\\end\{abstract\}", tex, re.DOTALL)
    if m:
        sections.append(Section("Abstract", m.start(), m.end()))
    matches = list(SECTION_RE.finditer(tex))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(tex)
        for marker in END_MARKERS:
            pos = tex.find(marker, match.end(), end)
            if pos != -1:
                end = pos
        sections.append(Section(match.group(1).strip(), match.start(), end))
    return sections


def _extract_latex_block(text: str) -> Optional[str]:
    m = re.search(r"```latex\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip("\n")
    m = re.search(r"```(?:tex)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip("\n") if m else None


def _extract_summary(text: str) -> str:
    m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            return data.get("summary") or json.dumps(data, ensure_ascii=False)
        except json.JSONDecodeError:
            return m.group(1).strip()[:2000]
    return ""


def revise_latex(
    tex: str,
    instruction: str,
    model_name: Optional[str] = None,
    target_section: Optional[str] = None,
    context: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    """Returns (revised_full_tex, change_summary)."""
    model_name = model_name or get_setting("llm.default_models.revision", "gemini-3.1-pro-preview")
    context = context or {}
    ctx_text = ""
    for label, value in context.items():
        if value:
            ctx_text += f"\n--- {label} ---\n{value[:60000]}\n"

    section = None
    if target_section and target_section != "(whole paper)":
        section = next((s for s in list_sections(tex) if s.title == target_section), None)
        if section is None:
            raise ValueError(f"Section '{target_section}' not found in the LaTeX source.")

    if section:
        part = tex[section.start : section.end]
        full_ctx = tex if len(tex) < 150000 else "(omitted: paper too long)"
        prompt = (
            f"AUTHOR INSTRUCTION:\n{instruction}\n\n"
            f"Apply it ONLY to the part titled '{section.title}' shown below. "
            "The full paper is given for context only.\n"
            f"{ctx_text}\n--- FULL PAPER (read-only context) ---\n{full_ctx}\n\n"
            f"--- PART TO REVISE ('{section.title}') ---\n{part}\n\n"
            "Output first a ```json block with {\"summary\": \"<what you changed>\"}, then the complete "
            "revised part (starting with the same \\section{...} or \\begin{abstract} line) in a ```latex block."
        )
    else:
        prompt = (
            f"AUTHOR INSTRUCTION:\n{instruction}\n\n{ctx_text}\n"
            f"--- CURRENT LATEX SOURCE ---\n{tex}\n\n"
            "Output first a ```json block with {\"summary\": \"<what you changed>\"}, then the FULL revised "
            "LaTeX document in a ```latex block."
        )

    rsp = call_llm_with_contents(
        contents=[prompt],
        model_name=model_name,
        generation_configs={"system_instruction": REVISION_SYSTEM_PROMPT, "temperature": 0.4},
        result_parsing_func=_extract_latex_block,
        check_parsed_response_not_none=True,
    )
    revised_part = rsp["parsed_response"]
    summary = _extract_summary(rsp["raw_response"]) or "(no summary returned)"
    if section:
        new_tex = tex[: section.start] + revised_part.rstrip() + "\n\n" + tex[section.end :].lstrip("\n")
    else:
        new_tex = revised_part
    if "\\begin{document}" in tex and "\\begin{document}" not in new_tex:
        raise ValueError("The model returned an incomplete document (missing \\begin{document}); not applied.")
    return new_tex, summary


def unified_diff(before: str, after: str, n: int = 2) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile="before.tex", tofile="after.tex", n=n,
        )
    )


# ---------------------------------------------------------------------------
# project-level helpers (final/ folder + revision history)
# ---------------------------------------------------------------------------


def final_paths(project_dir: str) -> Dict[str, str]:
    final_dir = os.path.join(project_dir, "final")
    return {
        "dir": final_dir,
        "tex": os.path.join(final_dir, "final_paper.tex"),
        "pdf": os.path.join(project_dir, "final_paper.pdf"),
        "revisions": os.path.join(project_dir, "revisions"),
    }


def compile_final(project_dir: str) -> Tuple[bool, str]:
    paths = final_paths(project_dir)
    if not os.path.exists(paths["tex"]):
        return False, "No final/final_paper.tex yet. Run the pipeline first."
    if not latex_available():
        return False, "pdflatex/bibtex not found. Install MiKTeX or TeX Live to compile PDFs."
    tmp_pdf = paths["pdf"] + ".new.pdf"
    if os.path.exists(tmp_pdf):
        os.remove(tmp_pdf)
    compile_latex(paths["dir"], tmp_pdf, "final_paper", timeout=int(get_setting("pipeline.latex_timeout", 120)))
    if not os.path.exists(tmp_pdf):
        log_path = os.path.join(paths["dir"], "final_paper.log")
        tail = ""
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            errs = [l for l in lines if l.startswith("!")]
            tail = "".join(errs[:10]) or "".join(lines[-30:])
        return False, "LaTeX compilation failed.\n" + tail
    os.replace(tmp_pdf, paths["pdf"])
    shutil.copy(paths["pdf"], os.path.join(paths["dir"], "final_paper.pdf"))
    return True, paths["pdf"]


def record_revision(project_dir: str, before: str, after: str, instruction: str, meta: Dict) -> str:
    paths = final_paths(project_dir)
    os.makedirs(paths["revisions"], exist_ok=True)
    existing = [d for d in os.listdir(paths["revisions"]) if d.startswith("rev_")]
    rev_dir = os.path.join(paths["revisions"], f"rev_{len(existing) + 1:03d}")
    os.makedirs(rev_dir)
    with open(os.path.join(rev_dir, "before.tex"), "w", encoding="utf-8") as f:
        f.write(before)
    with open(os.path.join(rev_dir, "after.tex"), "w", encoding="utf-8") as f:
        f.write(after)
    with open(os.path.join(rev_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"instruction": instruction, "time": time.time(), **meta}, f, indent=2, ensure_ascii=False)
    return rev_dir


def list_revisions(project_dir: str) -> List[Dict]:
    rev_root = final_paths(project_dir)["revisions"]
    out = []
    if not os.path.isdir(rev_root):
        return out
    for name in sorted(os.listdir(rev_root)):
        meta_path = os.path.join(rev_root, name, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            out.append({"id": name, "dir": os.path.join(rev_root, name), **meta})
    return out


def apply_revision(
    project_dir: str,
    instruction: str,
    target_section: Optional[str] = None,
    model_name: Optional[str] = None,
    compile_pdf: bool = True,
) -> Dict:
    paths = final_paths(project_dir)
    if not os.path.exists(paths["tex"]):
        raise FileNotFoundError("No final/final_paper.tex yet. Run the pipeline first.")
    with open(paths["tex"], "r", encoding="utf-8") as f:
        before = f.read()

    context = {}
    for label, rel in (
        ("EXPERIMENTAL LOG (data truth)", "raw_materials/experimental_log.md"),
        ("CITATION MAP (reference truth)", "literature_agent_output/citation_map.json"),
    ):
        path = os.path.join(project_dir, rel)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                context[label] = f.read()

    after, summary = revise_latex(before, instruction, model_name, target_section, context)
    with open(paths["tex"], "w", encoding="utf-8") as f:
        f.write(after)
    rev_dir = record_revision(
        project_dir, before, after, instruction,
        {"section": target_section or "(whole paper)", "model": model_name, "summary": summary},
    )
    result = {"revision_dir": rev_dir, "summary": summary, "compiled": False, "message": ""}
    if compile_pdf:
        ok, msg = compile_final(project_dir)
        result.update(compiled=ok, message=msg)
        print(("✅ " if ok else "⚠️ ") + msg)
    return result


def revert_to(project_dir: str, revision_id: str, which: str = "before") -> str:
    paths = final_paths(project_dir)
    src = os.path.join(paths["revisions"], revision_id, f"{which}.tex")
    with open(src, "r", encoding="utf-8") as f:
        content = f.read()
    with open(paths["tex"], "r", encoding="utf-8") as f:
        current = f.read()
    with open(paths["tex"], "w", encoding="utf-8") as f:
        f.write(content)
    record_revision(project_dir, current, content, f"Revert to {revision_id} ({which})", {"section": "(whole paper)", "summary": "manual revert"})
    return paths["tex"]
