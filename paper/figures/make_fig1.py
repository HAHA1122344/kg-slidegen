"""Generate Figure 1 (framework overview) for the paper.

Run:  python paper/figures/make_fig1.py

Produces ``framework.pdf`` (vector, for the manuscript) and
``framework.png`` (raster, for the README).  Chinese text needs an explicit
CJK font on macOS; the fallback list keeps it working on Linux too.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent

FONT_CANDIDATES = [
    "Hiragino Sans GB",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "Microsoft YaHei",
    "SimHei",
]
plt.rcParams["font.sans-serif"] = FONT_CANDIDATES + ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#1f2933"
MUTED = "#5c6b7a"
EDGE = "#8b9aa8"
PAPER = "#ffffff"
FILL_KG = "#e8eef6"
FILL_DERIVED = "#edf2ef"
FILL_MODEL = "#f7f0e5"
FILL_CHECK = "#f4eaec"
ACCENT = "#8c4a3f"

W, H = 11.9, 6.0


def box(ax, x, y, w, h, title, fill, *, sub=None, size=10.5, bold=True):
    """Rounded box with the title and an optional two-line caption.

    Title and caption are placed at fixed offsets from the box centre rather
    than proportional ones: proportional placement collapses on short boxes
    and the two strings end up on top of each other.
    """
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0,rounding_size=0.07",
            linewidth=1.1, edgecolor=EDGE, facecolor=fill, zorder=2,
        )
    )
    cy = y + h / 2
    ty = cy + (0.21 if sub else 0)
    ax.text(x + w / 2, ty, title, ha="center", va="center",
            fontsize=size, color=INK, zorder=3,
            fontweight="bold" if bold else "normal")
    if sub:
        ax.text(x + w / 2, cy - 0.20, sub, ha="center", va="top",
                fontsize=8.4, color=MUTED, zorder=3, linespacing=1.45)


def arrow(ax, start, end, *, dashed=False, color=EDGE, lw=1.2):
    ax.add_patch(
        FancyArrowPatch(
            start, end,
            arrowstyle="-|>", mutation_scale=13,
            linewidth=lw, color=color,
            linestyle=(0, (4, 3)) if dashed else "solid",
            shrinkA=2, shrinkB=2, zorder=1,
        )
    )


def main() -> None:
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.patch.set_facecolor(PAPER)

    for label, x in (("① 知识来源", 0.18), ("② 图谱与契约", 2.44), ("③ 生成与验收", 7.22)):
        ax.text(x, H - 0.28, label, fontsize=9, color=MUTED)

    # ------------------------------------------------------------ row 1
    src = [
        (4.46, "课程标准与大纲"),
        (3.82, "教材与讲义"),
        (3.18, "教师经验与作业统计"),
    ]
    for y, text in src:
        box(ax, 0.18, y, 1.72, 0.52, text, FILL_KG, size=9.4)

    box(ax, 2.44, 3.10, 2.14, 1.98, "课程知识图谱 G", FILL_KG,
        sub="8 类节点 · 10 类边\n含 Misconception 节点", size=11)

    # graph glyph in the upper-left corner, clear of the title
    gn = [(2.66, 4.78), (2.92, 4.52), (3.28, 4.80), (3.02, 4.94)]
    for i, (nx, ny) in enumerate(gn):
        ax.plot([nx], [ny], marker="o", markersize=6,
                color=ACCENT if i == 1 else MUTED, zorder=4)
    for a, b in ((0, 1), (1, 2), (0, 3), (3, 2)):
        ax.plot([gn[a][0], gn[b][0]], [gn[a][1], gn[b][1]],
                color=EDGE, linewidth=1.0, zorder=3)

    for y, _ in src:
        arrow(ax, (1.92, y + 0.26), (2.42, 4.09))

    box(ax, 4.96, 3.70, 1.80, 0.86, "约束编译", FILL_DERIVED,
        sub="子图 → 契约（constraints.py）", size=10.5)
    arrow(ax, (4.60, 4.09), (4.94, 4.09))

    box(ax, 7.22, 3.10, 1.98, 1.98, "契约 C(u)", FILL_DERIVED,
        sub="S 概念 · 顺序 拓扑序\nM 误区 · F 禁列\nB 背景 · k 页数", size=10.5)
    arrow(ax, (6.78, 4.09), (7.20, 4.09))

    box(ax, 9.58, 3.10, 1.44, 1.98, "LLM 生成", FILL_MODEL,
        sub="DeepSeek-V4\nJSON 契约", size=11)
    arrow(ax, (9.22, 4.09), (9.56, 4.09))

    # ------------------------------------------------------------ row 2
    box(ax, 9.58, 1.62, 1.44, 0.92, "渲染 pptx", FILL_MODEL,
        sub="全原生可编辑形状", size=10.5)
    arrow(ax, (10.30, 3.08), (10.30, 2.56))

    box(ax, 6.94, 1.50, 2.08, 1.16, "验证器", FILL_CHECK,
        sub="以同一份 C(u) 为真值\nvalidator.py", size=10.5)
    arrow(ax, (9.56, 2.08), (9.04, 2.08))

    box(ax, 4.40, 1.50, 2.14, 1.16, "六项指标与 findings", FILL_CHECK,
        sub="覆盖 · 跑题 · 背景\n顺序 · 误区 · 可编辑", size=10.5)
    arrow(ax, (6.92, 2.08), (6.56, 2.08))

    # the core idea: one contract, two roles
    arrow(ax, (7.98, 3.08), (7.98, 2.68), dashed=True, color=ACCENT, lw=1.4)
    ax.text(8.10, 2.88, "要求与验收同源", fontsize=8.6, color=ACCENT, va="center")

    arrow(ax, (4.38, 2.08), (2.84, 2.08))
    box(ax, 0.80, 1.50, 2.02, 1.16, "教师复核 / 定向重生成", "#f8f8f8",
        sub="只重做未通过的页\n契约与图谱不变", size=10.5)

    # Loop the failed pages back to generation.  It has to run outside the
    # box column, otherwise the return path would cross the render box and
    # read as if regeneration happened after rendering.
    ax.plot([1.81, 1.81], [1.48, 0.86], color=EDGE, linewidth=1.2, zorder=1)
    ax.plot([1.81, 11.55], [0.86, 0.86], color=EDGE, linewidth=1.2, zorder=1)
    ax.plot([11.55, 11.55], [0.86, 4.09], color=EDGE, linewidth=1.2, zorder=1)
    arrow(ax, (11.55, 4.09), (11.06, 4.09), dashed=True)

    ax.text(6.40, 0.96, "只把未通过的页送回生成，图谱与契约不变", fontsize=8.6,
            color=MUTED, ha="center", va="bottom")

    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    for suffix in ("pdf", "png"):
        fig.savefig(
            OUT / f"framework.{suffix}",
            dpi=220 if suffix == "png" else None,
            facecolor=PAPER, bbox_inches="tight",
        )
    print(f"已生成 {OUT/'framework.pdf'} 与 {OUT/'framework.png'}")


if __name__ == "__main__":
    main()
