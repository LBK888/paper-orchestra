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

"""Export the finished paper to PDF / DOCX / Markdown / LaTeX zip.

DOCX and Markdown use pandoc (bundled by ``pypandoc_binary``) with citeproc
for the bibliography. Without pandoc a simpler built-in converter is used.
"""

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from typing import Optional, Tuple

EXPORT_DIRNAME = "exports"

# pandoc template for Markdown: title + abstract as Markdown instead of YAML metadata.
MD_TEMPLATE = """$if(title)$
# $title$

$endif$
$if(abstract)$
## Abstract

$abstract$

$endif$
$body$
"""


def pandoc_path() -> Optional[str]:
    try:
        import pypandoc  # type: ignore

        path = pypandoc.get_pandoc_path()
        for cand in (path, (path or "") + ".exe"):
            if cand and os.path.isfile(cand):
                return cand
    except Exception:
        pass
    return shutil.which("pandoc")


def _final_tex(project_dir: str) -> Tuple[str, str]:
    final_dir = os.path.join(project_dir, "final")
    tex = os.path.join(final_dir, "final_paper.tex")
    if not os.path.exists(tex):
        raise FileNotFoundError("No final/final_paper.tex yet. Run the pipeline (at least to 'sections').")
    return final_dir, tex


def _exports_dir(project_dir: str) -> str:
    path = os.path.join(project_dir, EXPORT_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def _prepare_tree(final_dir: str) -> Tuple[str, str]:
    """Copies final/ to a temp dir, rasterises PDF figures to PNG and points
    \\includegraphics at them (Word/Markdown cannot embed PDF figures)."""
    tmp = tempfile.mkdtemp(prefix="po_export_")
    work = os.path.join(tmp, "paper")
    shutil.copytree(final_dir, work)
    try:
        import pymupdf  # type: ignore
    except ImportError:
        pymupdf = None
    figs_converted = {}
    for root, _, files in os.walk(work):
        for name in files:
            if name.lower().endswith((".sty", ".cls", ".bst")):
                # pandoc would try to parse local style files and leak macro text
                os.remove(os.path.join(root, name))
                continue
            if name.lower().endswith(".pdf") and name != "final_paper.pdf" and pymupdf:
                pdf_path = os.path.join(root, name)
                try:
                    doc = pymupdf.open(pdf_path)
                    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(3, 3))
                    png_path = os.path.splitext(pdf_path)[0] + ".png"
                    pix.save(png_path)
                    rel = os.path.relpath(pdf_path, work).replace("\\", "/")
                    figs_converted[rel] = os.path.splitext(rel)[0] + ".png"
                except Exception as exc:
                    print(f"[export] could not rasterise {name}: {exc}")
    tex_path = os.path.join(work, "final_paper.tex")
    with open(tex_path, "r", encoding="utf-8") as f:
        tex = f.read()
    for pdf_rel, png_rel in figs_converted.items():
        tex = tex.replace(pdf_rel, png_rel)
        tex = tex.replace(os.path.splitext(pdf_rel)[0] + "}", png_rel + "}")
    # Inline \input{...} files so pandoc sees macros (e.g. preamble.tex, math_commands.tex)
    def inline_input(match):
        name = match.group(1)
        cand = os.path.join(work, name if name.endswith(".tex") else name + ".tex")
        if os.path.exists(cand):
            with open(cand, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        return match.group(0)

    tex = re.sub(r"\\input\{([^}]+)\}", inline_input, tex)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)
    return work, tex_path


def _sanitize_bib(path: str) -> None:
    """pandoc's BibTeX reader rejects ``@String(X = {...})``; use braces instead."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    fixed = re.sub(r"(?im)^(\s*@string)\s*\((.*)\)\s*$", r"\1{\2}", text)
    if fixed != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(fixed)


def _bib_args(work: str):
    bibs = [os.path.join(work, f) for f in os.listdir(work) if f.endswith(".bib")]
    for b in bibs:
        _sanitize_bib(b)
    args = []
    if bibs:
        args.append("--citeproc")
        for b in bibs:
            args.append(f"--bibliography={b}")
    return args


def _run_pandoc(work: str, tex_path: str, out_path: str, to: str, extra=None) -> None:
    pandoc = pandoc_path()
    base = [
        pandoc, tex_path, "-f", "latex", "-t", to, "-o", out_path,
        "--standalone", f"--resource-path={work}",
    ] + (extra or [])
    bib = _bib_args(work)
    proc = subprocess.run(base + bib, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if proc.returncode != 0 and bib:
        print(f"[pandoc] bibliography processing failed, retrying without citeproc: {proc.stderr.strip()[-500:]}")
        proc = subprocess.run(base, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"pandoc failed ({proc.returncode}): {proc.stderr[-2000:]}")
    if proc.stderr.strip():
        print(f"[pandoc] {proc.stderr.strip()[-1500:]}")


# ---------------------------------------------------------------------------
# fallback converter (no pandoc)
# ---------------------------------------------------------------------------


def latex_to_markdown_basic(tex: str) -> str:
    body = tex
    if "\\begin{document}" in body:
        body = body.split("\\begin{document}", 1)[1]
    body = body.split("\\end{document}", 1)[0]
    body = re.sub(r"(?<!\\)%.*", "", body)
    title = re.search(r"\\title\{([^}]*)\}", tex)
    out = f"# {title.group(1)}\n\n" if title else ""
    body = re.sub(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", r"## Abstract\n\n\1\n", body, flags=re.S)
    body = re.sub(r"\\section\*?\{([^}]*)\}", r"\n## \1\n", body)
    body = re.sub(r"\\subsection\*?\{([^}]*)\}", r"\n### \1\n", body)
    body = re.sub(r"\\subsubsection\*?\{([^}]*)\}", r"\n#### \1\n", body)
    body = re.sub(r"\\paragraph\{([^}]*)\}", r"\n**\1** ", body)

    def braced_arg(text: str, command: str) -> str:
        """Argument of ``\\command{...}`` with nested braces balanced."""
        start = text.find("\\" + command + "{")
        if start == -1:
            return ""
        i = start + len(command) + 2
        depth = 1
        for j in range(i, len(text)):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                return text[i:j]
        return text[i:]

    def figure(m):
        block = m.group(0)
        img = re.search(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", block)
        if not img:
            return ""
        caption = " ".join(braced_arg(block, "caption").split())
        return f"\n![{caption}]({img.group(1)})\n"

    body = re.sub(r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", figure, body, flags=re.S)
    body = re.sub(r"\\begin\{(itemize|enumerate)\}", "", body)
    body = re.sub(r"\\end\{(itemize|enumerate)\}", "", body)
    body = re.sub(r"\\item\s*", "\n- ", body)
    body = re.sub(r"\\textbf\{([^}]*)\}", r"**\1**", body)
    body = re.sub(r"\\(?:emph|textit)\{([^}]*)\}", r"*\1*", body)
    body = re.sub(r"\\texttt\{([^}]*)\}", r"`\1`", body)
    body = re.sub(r"\\(?:cite|citep|citet)\{([^}]*)\}", lambda m: "[" + "; ".join(k.strip() for k in m.group(1).split(",")) + "]", body)
    body = re.sub(r"\\(?:ref|eqref|autoref|cref)\{([^}]*)\}", r"\1", body)
    body = re.sub(r"\\label\{[^}]*\}", "", body)
    body = re.sub(r"\\(?:maketitle|centering|small|footnotesize|vspace\{[^}]*\}|hfill|noindent)", "", body)
    body = re.sub(r"\\bibliography(?:style)?\{[^}]*\}", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return out + body.strip() + "\n"


def markdown_to_docx_basic(md: str, out_path: str, resource_dir: str) -> None:
    from docx import Document  # type: ignore
    from docx.shared import Inches  # type: ignore

    doc = Document()
    for block in re.split(r"\n\s*\n", md):
        block = block.strip()
        if not block:
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", block)
        if m:
            doc.add_heading(m.group(2).strip(), level=min(len(m.group(1)), 4))
            continue
        img = re.match(r"^!\[(.*?)\]\((.*?)\)$", block, re.S)
        if img:
            path = os.path.join(resource_dir, img.group(2))
            for ext in ("", ".png", ".jpg"):
                if os.path.exists(path + ext):
                    doc.add_picture(path + ext, width=Inches(6))
                    break
            doc.add_paragraph(img.group(1)).italic = True
            continue
        if block.startswith("- "):
            for line in block.splitlines():
                doc.add_paragraph(line.lstrip("- ").strip(), style="List Bullet")
            continue
        doc.add_paragraph(re.sub(r"\*\*|\*|`", "", block.replace("\n", " ")))
    doc.save(out_path)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def export_pdf(project_dir: str, out_path: Optional[str] = None) -> str:
    src = os.path.join(project_dir, "final_paper.pdf")
    if not os.path.exists(src):
        from methods.agents.manual_revision_agent import compile_final

        ok, msg = compile_final(project_dir)
        if not ok:
            raise RuntimeError(msg)
    out_path = out_path or os.path.join(_exports_dir(project_dir), "paper.pdf")
    shutil.copy(src, out_path)
    return out_path


def export_markdown(project_dir: str, out_path: Optional[str] = None) -> str:
    final_dir, _ = _final_tex(project_dir)
    out_dir = _exports_dir(project_dir)
    out_path = out_path or os.path.join(out_dir, "paper.md")
    work, tex_path = _prepare_tree(final_dir)
    try:
        media_dir = os.path.join(os.path.dirname(out_path), "paper_media")
        if pandoc_path():
            # Render inside the work dir so image links stay relative (paper_media/...),
            # then move the .md and its media next to out_path.
            template = os.path.join(work, "_po_md_template.md")
            with open(template, "w", encoding="utf-8") as f:
                f.write(MD_TEMPLATE)
            tmp_md = os.path.join(work, "paper.md")
            _run_pandoc(
                work, tex_path, tmp_md, "gfm",
                ["--extract-media=paper_media", "--wrap=none", f"--template={template}"],
            )
            if os.path.isdir(media_dir):
                shutil.rmtree(media_dir)
            if os.path.isdir(os.path.join(work, "paper_media")):
                shutil.move(os.path.join(work, "paper_media"), media_dir)
            with open(tmp_md, "r", encoding="utf-8") as f:
                md = f.read().replace("](paper_media\\", "](paper_media/").replace('src="paper_media\\', 'src="paper_media/')
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(md)
        else:
            with open(tex_path, "r", encoding="utf-8") as f:
                md = latex_to_markdown_basic(f.read())
            os.makedirs(media_dir, exist_ok=True)
            for root, _, files in os.walk(work):
                for name in files:
                    if name.lower().endswith((".png", ".jpg", ".jpeg")):
                        shutil.copy(os.path.join(root, name), os.path.join(media_dir, name))
            md = re.sub(r"\]\((?:figures/)?([^)]+)\)", lambda m: f"](paper_media/{os.path.basename(m.group(1))})", md)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(md)
    finally:
        shutil.rmtree(os.path.dirname(work), ignore_errors=True)
    return out_path


def export_docx(project_dir: str, out_path: Optional[str] = None, reference_docx: Optional[str] = None) -> str:
    final_dir, _ = _final_tex(project_dir)
    out_path = out_path or os.path.join(_exports_dir(project_dir), "paper.docx")
    work, tex_path = _prepare_tree(final_dir)
    try:
        if pandoc_path():
            extra = [f"--reference-doc={reference_docx}"] if reference_docx else []
            _run_pandoc(work, tex_path, out_path, "docx", extra)
        else:
            with open(tex_path, "r", encoding="utf-8") as f:
                md = latex_to_markdown_basic(f.read())
            markdown_to_docx_basic(md, out_path, work)
    finally:
        shutil.rmtree(os.path.dirname(work), ignore_errors=True)
    return out_path


def export_latex_zip(project_dir: str, out_path: Optional[str] = None) -> str:
    final_dir, _ = _final_tex(project_dir)
    out_path = out_path or os.path.join(_exports_dir(project_dir), "paper_latex.zip")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(final_dir):
            for name in files:
                if name.endswith((".aux", ".log", ".out", ".blg")):
                    continue
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, final_dir))
    return out_path


def export_all(project_dir: str, formats=("pdf", "docx", "md", "latex")) -> dict:
    results = {}
    funcs = {"pdf": export_pdf, "docx": export_docx, "md": export_markdown, "latex": export_latex_zip}
    for fmt in formats:
        try:
            results[fmt] = {"ok": True, "path": funcs[fmt](project_dir)}
        except Exception as exc:
            results[fmt] = {"ok": False, "error": str(exc)}
    return results
