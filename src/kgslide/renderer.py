"""Render structured slide payloads into an editable .pptx file.

Design notes
------------
* Blank layout is used for every slide so that geometry is fully controlled.
* All content is placed in native shapes (text boxes and rounded rectangles);
  no rasterised images are embedded, which keeps ``editability`` at 1.0 and
  lets the teacher adjust text directly in PowerPoint or WPS.
* East-Asian typefaces are set explicitly, otherwise Chinese text falls back to
  a default font and line spacing breaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt
from lxml import etree

# ------------------------------------------------------------------ palette
INK = RGBColor(0x1F, 0x29, 0x37)
BODY = RGBColor(0x37, 0x41, 0x51)
MUTED = RGBColor(0x6B, 0x72, 0x80)
ACCENT = RGBColor(0x25, 0x63, 0xEB)
DANGER = RGBColor(0xDC, 0x26, 0x26)
CODE_BG = RGBColor(0xF3, 0xF4, 0xF6)
LINE = RGBColor(0xE5, 0xE7, 0xEB)

FONT_SANS = "思源黑体"
FONT_MONO = "JetBrains Mono"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
MARGIN = Inches(0.9)
CONTENT_W = SLIDE_W - MARGIN * 2


@dataclass
class RenderResult:
    path: Path
    slide_count: int
    native_ratio: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "slide_count": self.slide_count,
            "native_ratio": round(self.native_ratio, 4),
        }


def _apply_font(run, size: int, bold: bool = False, color: RGBColor = BODY, mono: bool = False) -> None:
    """Set latin, east-asian and complex-script typefaces on a run."""
    face = FONT_MONO if mono else FONT_SANS
    font = run.font
    font.size = Pt(size)
    font.bold = bold
    font.color.rgb = color
    font.name = face

    rpr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        element = rpr.find(qn(tag))
        if element is None:
            element = etree.SubElement(rpr, qn(tag))
        element.set("typeface", face)


def _textbox(slide, left, top, width, height, *, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0
    return box


def _add_text(slide, text, left, top, width, height, size, *, bold=False, color=BODY, mono=False, align=PP_ALIGN.LEFT):
    box = _textbox(slide, left, top, width, height)
    paragraph = box.text_frame.paragraphs[0]
    paragraph.alignment = align
    run = paragraph.add_run()
    run.text = text
    _apply_font(run, size, bold=bold, color=color, mono=mono)
    return box


def _add_rule(slide, top, color=LINE, thickness=Emu(9525)) -> None:
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, MARGIN, top, CONTENT_W, thickness)
    line.fill.solid()
    line.fill.fore_color.rgb = color
    line.line.fill.background()
    line.shadow.inherit = False


def _add_footer(slide, index: int, total: int, unit_name: str) -> None:
    _add_text(slide, unit_name, MARGIN, SLIDE_H - Inches(0.55), Inches(8), Inches(0.3), 10, color=MUTED)
    _add_text(
        slide,
        f"{index} / {total}",
        SLIDE_W - MARGIN - Inches(1.2),
        SLIDE_H - Inches(0.55),
        Inches(1.2),
        Inches(0.3),
        10,
        color=MUTED,
        align=PP_ALIGN.RIGHT,
    )


def _render_title(slide, data, ctx) -> None:
    _add_text(slide, "课程课件", MARGIN, Inches(1.5), Inches(6), Inches(0.35), 14, color=ACCENT, bold=True)
    _add_text(slide, data.get("title", ""), MARGIN, Inches(2.0), CONTENT_W, Inches(1.6), 44, bold=True, color=INK)
    _add_rule(slide, Inches(3.75), ACCENT, Emu(38100))
    bullets = data.get("bullets") or []
    if bullets:
        _add_text(slide, bullets[0], MARGIN, Inches(4.15), Inches(10), Inches(1.0), 18, color=MUTED)


def _render_objectives(slide, data, ctx) -> None:
    _add_text(slide, data.get("title", "学习目标"), MARGIN, Inches(0.7), CONTENT_W, Inches(0.7), 30, bold=True, color=INK)
    _add_rule(slide, Inches(1.55), LINE)
    top = Inches(1.95)
    for i, item in enumerate(data.get("bullets") or []):
        _add_text(slide, f"{i + 1:02d}", MARGIN, top + Inches(0.75) * i, Inches(0.6), Inches(0.5), 16, bold=True, color=ACCENT)
        _add_text(slide, item, MARGIN + Inches(0.7), top + Inches(0.75) * i, CONTENT_W - Inches(0.7), Inches(0.5), 19, color=BODY)


def _render_concept(slide, data, ctx) -> None:
    _add_text(slide, data.get("title", ""), MARGIN, Inches(0.7), CONTENT_W, Inches(0.9), 30, bold=True, color=INK)
    _add_rule(slide, Inches(1.6), LINE)
    top = Inches(2.0)
    for i, bullet in enumerate(data.get("bullets") or []):
        _add_text(slide, "—", MARGIN, top + Inches(0.8) * i, Inches(0.35), Inches(0.5), 16, color=ACCENT, bold=True)
        _add_text(slide, bullet, MARGIN + Inches(0.45), top + Inches(0.8) * i, CONTENT_W - Inches(0.45), Inches(0.7), 18, color=BODY)


def _render_code(slide, data, ctx) -> None:
    _add_text(slide, data.get("title", ""), MARGIN, Inches(0.7), CONTENT_W, Inches(0.9), 30, bold=True, color=INK)
    _add_rule(slide, Inches(1.6), LINE)
    top = Inches(2.0)
    bullets = data.get("bullets") or []
    for i, bullet in enumerate(bullets[:2]):
        _add_text(slide, bullet, MARGIN, top + Inches(0.62) * i, CONTENT_W, Inches(0.5), 16, color=BODY)

    code = (data.get("code") or "").strip()
    if not code:
        return
    code_top = top + Inches(0.62) * len(bullets[:2]) + Inches(0.25)
    height = SLIDE_H - code_top - Inches(0.85)
    panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, MARGIN, code_top, CONTENT_W, height)
    panel.fill.solid()
    panel.fill.fore_color.rgb = CODE_BG
    panel.line.color.rgb = LINE
    panel.line.width = Pt(0.75)
    panel.shadow.inherit = False

    box = _textbox(slide, MARGIN + Inches(0.35), code_top + Inches(0.25), CONTENT_W - Inches(0.7), height - Inches(0.5))
    frame = box.text_frame
    lines = code.splitlines()[:18]
    for i, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.alignment = PP_ALIGN.LEFT
        run = paragraph.add_run()
        run.text = line if line.strip() else " "
        _apply_font(run, 13, color=INK, mono=True)


def _render_comparison(slide, data, ctx) -> None:
    _render_concept(slide, data, ctx)


def _render_misconception(slide, data, ctx) -> None:
    _add_text(slide, data.get("title", "常见错误"), MARGIN, Inches(0.7), CONTENT_W, Inches(0.9), 30, bold=True, color=DANGER)
    _add_rule(slide, Inches(1.6), DANGER, Emu(19050))

    bullets = data.get("bullets") or []
    wrong = bullets[0] if bullets else ""
    right = bullets[1] if len(bullets) > 1 else ""

    if wrong:
        panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, MARGIN, Inches(2.0), CONTENT_W, Inches(1.35))
        panel.fill.solid()
        panel.fill.fore_color.rgb = RGBColor(0xFE, 0xF2, 0xF2)
        panel.line.color.rgb = RGBColor(0xF7, 0xC1, 0xC1)
        panel.line.width = Pt(0.75)
        panel.shadow.inherit = False
        _add_text(slide, "×", MARGIN + Inches(0.35), Inches(2.3), Inches(0.6), Inches(0.6), 28, bold=True, color=DANGER)
        _add_text(slide, wrong, MARGIN + Inches(1.0), Inches(2.28), CONTENT_W - Inches(1.4), Inches(0.9), 17, color=BODY)

    if right:
        panel2 = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, MARGIN, Inches(3.65), CONTENT_W, Inches(1.85))
        panel2.fill.solid()
        panel2.fill.fore_color.rgb = RGBColor(0xEC, 0xFD, 0xF5)
        panel2.line.color.rgb = RGBColor(0xA7, 0xF3, 0xD0)
        panel2.line.width = Pt(0.75)
        panel2.shadow.inherit = False
        _add_text(slide, "✓", MARGIN + Inches(0.35), Inches(3.95), Inches(0.6), Inches(0.6), 26, bold=True, color=RGBColor(0x05, 0x96, 0x69))
        _add_text(slide, right, MARGIN + Inches(1.0), Inches(3.92), CONTENT_W - Inches(1.4), Inches(1.4), 17, color=BODY)


def _render_summary(slide, data, ctx) -> None:
    _render_concept(slide, data, ctx)


RENDERERS = {
    "title": _render_title,
    "objectives": _render_objectives,
    "concept": _render_concept,
    "comparison": _render_comparison,
    "code": _render_code,
    "misconception": _render_misconception,
    "summary": _render_summary,
}


def render(payload: dict[str, Any], output_path: str | Path, unit_name: str = "") -> RenderResult:
    """Render a slide payload and return statistics used by the validator."""
    presentation = Presentation()
    presentation.slide_width = SLIDE_W
    presentation.slide_height = SLIDE_H
    blank = presentation.slide_layouts[6]

    slides = payload.get("slides", [])
    total = len(slides)
    for position, data in enumerate(slides, start=1):
        slide = presentation.slides.add_slide(blank)
        layout = data.get("layout", "concept")
        renderer = RENDERERS.get(layout, _render_concept)
        renderer(slide, data, None)
        if layout != "title":
            _add_footer(slide, position, total, unit_name or payload.get("unit_id", ""))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(output)

    native = sum(
        1
        for slide in presentation.slides
        for shape in slide.shapes
        if shape.shape_type is not None and "PICTURE" not in str(shape.shape_type)
    )
    all_shapes = sum(len(slide.shapes) for slide in presentation.slides)
    ratio = native / all_shapes if all_shapes else 1.0

    return RenderResult(path=output, slide_count=total, native_ratio=ratio)
