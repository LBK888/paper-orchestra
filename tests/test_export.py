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

"""DOCX / Markdown export, including the real conference templates."""

import os
import shutil
import zipfile

import pytest

from tests.mock_backend import ROOT
from utils.export_utils import (
    export_docx,
    export_latex_zip,
    export_markdown,
    latex_to_markdown_basic,
    pandoc_path,
)

needs_pandoc = pytest.mark.skipif(not pandoc_path(), reason="pandoc not available (pip install pypandoc_binary)")


def _project_from_template(tmp_path, template):
    proj = tmp_path / template
    final = proj / "final"
    shutil.copytree(os.path.join(ROOT, "templates", template), final)
    shutil.copy(final / "template.tex", final / "final_paper.tex")
    return str(proj)


@needs_pandoc
@pytest.mark.parametrize("template", ["cvpr2025", "iclr2025"])
def test_conference_templates_export(tmp_path, template):
    proj = _project_from_template(tmp_path, template)
    docx = export_docx(proj)
    with zipfile.ZipFile(docx) as zf:
        assert "word/document.xml" in zf.namelist()
    md = open(export_markdown(proj), encoding="utf-8").read()
    assert md.startswith("# ")
    assert "## Abstract" in md
    assert "# Introduction" in md
    assert "maketitle" not in md  # local .sty files must not leak macro text
    assert "bibliography:" not in md  # no temp paths in front matter


@needs_pandoc
def test_markdown_figures_use_relative_media_and_docx_embeds_image(tmp_path):
    from PIL import Image

    proj = tmp_path / "p"
    final = proj / "final"
    (final / "figures").mkdir(parents=True)
    Image.new("RGB", (64, 32), "green").save(final / "figures" / "f.png")
    (final / "final_paper.tex").write_text(
        "\\documentclass{article}\\usepackage{graphicx}\\begin{document}\n"
        "\\section{Results}\nText.\n\\begin{figure}\\includegraphics{figures/f.png}\\caption{Cap.}\\end{figure}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    md_path = export_markdown(str(proj))
    md = open(md_path, encoding="utf-8").read()
    assert 'src="paper_media/' in md or "](paper_media/" in md
    assert ":\\" not in md and ":/" not in md.replace("https://", "")  # no absolute paths
    media_dir = os.path.join(os.path.dirname(md_path), "paper_media")
    assert any(f.endswith(".png") for _, _, files in os.walk(media_dir) for f in files)
    with zipfile.ZipFile(export_docx(str(proj))) as zf:
        assert any(n.startswith("word/media/") for n in zf.namelist())


def test_latex_zip_excludes_build_artifacts(tmp_path):
    proj = _project_from_template(tmp_path, "cvpr2025")
    (tmp_path / "cvpr2025" / "final" / "final_paper.aux").write_text("x")
    with zipfile.ZipFile(export_latex_zip(proj)) as zf:
        names = zf.namelist()
    assert "final_paper.tex" in names and "final_paper.aux" not in names


def test_basic_converter_without_pandoc():
    md = latex_to_markdown_basic(
        "\\title{T}\\begin{document}\\begin{abstract}Abs.\\end{abstract}\n"
        "\\section{Intro}\nSee \\cite{a,b} and \\textbf{bold}.\n"
        "\\begin{itemize}\\item one\\item two\\end{itemize}\n"
        "\\begin{figure}\\includegraphics[width=1cm]{figures/x.png}\\caption{Cap}\\end{figure}\n"
        "\\end{document}"
    )
    assert md.startswith("# T")
    assert "## Abstract" in md and "## Intro" in md
    assert "[a; b]" in md and "**bold**" in md
    assert "- one" in md and "![Cap](figures/x.png)" in md
