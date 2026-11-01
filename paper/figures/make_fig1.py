"""Generate Figure 1 (framework overview) for the paper.

Run:  python paper/figures/make_fig1.py            # both languages
      python paper/figures/make_fig1.py --lang en  # English only

Outputs ``framework.pdf`` / ``framework.png`` (Chinese, for the README) and
``framework_en.pdf`` / ``framework_en.png`` (English, for the manuscript).
Chinese text needs an explicit CJK font on macOS; the fallback list keeps it
working on Linux too.
"""

from __future__ import annotations

import argparse
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

STRINGS = {
    "zh": {
        "stage1": "① 知识来源",
        "stage2": "② 图谱与契约",
        "stage3": "③ 生成与验收",
        "src": ["课程标准与大纲", "教材与讲义", "教师经验与作业统计"],
        "kg": "课程知识图谱 G",
        "kg_sub": "8 类节点 · 10 类边\n含 Misconception 节点",
        "compile": "约束编译",
        "compile_sub": "子图 → 契约（constraints.py）",
        "contract": "契约 C(u)",
        "contract_sub": "S 概念 · 顺序 拓扑序\nM 误区 · F 禁列\nB 背景 · k 页数",
        "gen": "LLM 生成",
        "gen_sub": "DeepSeek-V4\nJSON 契约",
        "render": "渲染 pptx",
        "render_sub": "全原生可编辑形状",
        "valid": "验证器",
        "valid_sub": "以同一份 C(u) 为真值\nvalidator.py",
        "metrics": "六项指标与 findings",
        "metrics_sub": "覆盖 · 跑题 · 背景\n顺序 · 误区 · 可编辑",
        "same_source": "要求与验收同源",
        "review": "教师复核 / 定向重生成",
        "review_sub": "只重做未通过的页\n契约与图谱不变",
        "loop": "只把未通过的页送回生成，图谱与契约不变",
        "suffix": "",
        "log": "已生成",
        "geo": dict(src_w=1.72, src_fs=9.4, compile_fs=10.5, contract_w=1.98,
                    gen_fs=11.0, sub_fs=8.4, review_fs=10.5, arrow_y=4.09),
    },
    "en": {
        "stage1": "① Knowledge sources",
        "stage2": "② Graph and contract",
        "stage3": "③ Generation and acceptance",
        "src": ["Curriculum\nstandard", "Textbook and\nhandouts",
                "Teacher experience\nand error logs"],
        "kg": "Curriculum graph  G",
        "kg_sub": "8 node types · 10 edge types\nincl. Misconception",
        "compile": "Constraint\ncompilation",
        "compile_sub": "subgraph → contract",
        "contract": "Contract  C(u)",
        "contract_sub": "S concepts · order\nM misconceptions · F forbidden\nB background · k budget",
        "gen": "LLM\ngeneration",
        "gen_sub": "DeepSeek-V4\nJSON contract",
        "render": "Render .pptx",
        "render_sub": "all-native shapes",
        "valid": "Validator",
        "valid_sub": "same C(u) as ground truth\nvalidator.py",
        "metrics": "Six metrics\n+ findings",
        "metrics_sub": "coverage · scope · recap\norder · misconception · edit",
        "same_source": "same C(u)",
        "review": "Teacher review /\ntargeted regeneration",
        "review_sub": "only failed pages redone\ncontract and graph fixed",
        "loop": "only failed pages are sent back; graph and contract unchanged",
        "suffix": "_en",
        "log": "wrote",
        "geo": dict(src_w=1.95, src_fs=8.5, compile_fs=9.6, contract_w=2.06,
                    gen_fs=9.8, sub_fs=7.9, review_fs=9.5, arrow_y=4.09),
    },
}


SUB_FS = {"zh": 8.4, "en": 7.9}
_CUR_LANG = "zh"


def box(ax, x, y, w, h, title, fill, *, sub=None, size=10.5, bold=True):
    """Rounded box with the title and an optional caption.

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
        ax.text(x + w / 2, cy - 0.22, sub, ha="center", va="top",
                fontsize=SUB_FS[_CUR_LANG], color=MUTED, zorder=3, linespacing=1.4)


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


def build(lang: str) -> None:
    global _CUR_LANG
    _CUR_LANG = lang
    t = STRINGS[lang]
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.patch.set_facecolor(PAPER)

    for label, x in ((t["stage1"], 0.18), (t["stage2"], 2.44), (t["stage3"], 7.22)):
        ax.text(x, H - 0.28, label, fontsize=9, color=MUTED)

    # ------------------------------------------------------------ row 1
    src = [
        (4.46, t["src"][0]),
        (3.82, t["src"][1]),
        (3.18, t["src"][2]),
    ]
    g = t["geo"]
    for y, text in src:
        box(ax, 0.18, y, g["src_w"], 0.52, text, FILL_KG, size=g["src_fs"])

    box(ax, 2.44, 3.10, 2.14, 1.98, t["kg"], FILL_KG,
        sub=t["kg_sub"], size=11)

    # graph glyph in the upper-left corner, clear of the title
    gn = [(2.66, 4.78), (2.92, 4.52), (3.28, 4.80), (3.02, 4.94)]
    for i, (nx, ny) in enumerate(gn):
        ax.plot([nx], [ny], marker="o", markersize=6,
                color=ACCENT if i == 1 else MUTED, zorder=4)
    for a, b in ((0, 1), (1, 2), (0, 3), (3, 2)):
        ax.plot([gn[a][0], gn[b][0]], [gn[a][1], gn[b][1]],
                color=EDGE, linewidth=1.0, zorder=3)

    for y, _ in src:
        arrow(ax, (0.18 + g["src_w"] + 0.02, y + 0.26), (2.42, 4.09))

    box(ax, 4.96, 3.62, 1.80, 1.00, t["compile"], FILL_DERIVED,
        sub=t["compile_sub"], size=g["compile_fs"])
    arrow(ax, (4.60, 4.09), (4.94, 4.09))

    box(ax, 7.22, 3.10, g["contract_w"], 1.98, t["contract"], FILL_DERIVED,
        sub=t["contract_sub"], size=g["compile_fs"])
    arrow(ax, (6.78, 4.09), (7.20, 4.09))

    gen_x = 7.22 + g["contract_w"] + 0.36
    box(ax, gen_x, 3.10, 1.44, 1.98, t["gen"], FILL_MODEL,
        sub=t["gen_sub"], size=g["gen_fs"])
    arrow(ax, (7.22 + g["contract_w"] + 0.02, 4.09), (gen_x - 0.02, 4.09))

    # ------------------------------------------------------------ row 2
    box(ax, gen_x, 1.62, 1.44, 0.92, t["render"], FILL_MODEL,
        sub=t["render_sub"], size=g["compile_fs"])
    arrow(ax, (gen_x + 0.72, 3.08), (gen_x + 0.72, 2.56))

    box(ax, 6.94, 1.50, 2.08, 1.16, t["valid"], FILL_CHECK,
        sub=t["valid_sub"], size=g["compile_fs"])
    arrow(ax, (gen_x - 0.02, 2.08), (9.04, 2.08))

    box(ax, 4.40, 1.50, 2.14, 1.16, t["metrics"], FILL_CHECK,
        sub=t["metrics_sub"], size=g["compile_fs"])
    arrow(ax, (6.92, 2.08), (6.56, 2.08))

    # the core idea: one contract, two roles
    arrow(ax, (7.98, 3.08), (7.98, 2.68), dashed=True, color=ACCENT, lw=1.4)
    ax.text(8.10, 2.88, t["same_source"], fontsize=8.0, color=ACCENT, va="center")

    arrow(ax, (4.38, 2.08), (2.84, 2.08))
    box(ax, 0.80, 1.50, 2.02, 1.16, t["review"], "#f8f8f8",
        sub=t["review_sub"], size=g["review_fs"])

    # Loop the failed pages back to generation.  It has to run outside the
    # box column, otherwise the return path would cross the render box and
    # read as if regeneration happened after rendering.
    ax.plot([1.81, 1.81], [1.48, 0.86], color=EDGE, linewidth=1.2, zorder=1)
    ax.plot([1.81, 11.55], [0.86, 0.86], color=EDGE, linewidth=1.2, zorder=1)
    ax.plot([11.55, 11.55], [0.86, 4.09], color=EDGE, linewidth=1.2, zorder=1)
    arrow(ax, (11.55, 4.09), (11.06, 4.09), dashed=True)

    ax.text(6.40, 0.96, t["loop"], fontsize=8.6,
            color=MUTED, ha="center", va="bottom")

    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    for suffix in ("pdf", "png"):
        path = OUT / f"framework{t['suffix']}.{suffix}"
        fig.savefig(
            path,
            dpi=220 if suffix == "png" else None,
            facecolor=PAPER, bbox_inches="tight",
        )
        print(f"{t['log']} {path}")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["zh", "en", "both"], default="both")
    args = ap.parse_args()
    langs = ["zh", "en"] if args.lang == "both" else [args.lang]
    for lang in langs:
        build(lang)


if __name__ == "__main__":
    main()
