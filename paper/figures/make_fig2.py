"""Generate Figure 2 (graph fragment and its compiled contract) for the paper.

Run:  python paper/figures/make_fig2.py

Left panel  : the U11 subgraph as it exists in ``data/kg_pyds_m4.json``
              (prerequisite edges, one cross-session edge, one misconception,
              one skill linked by ``implements``).
Right panel : the contract that ``build_constraints`` compiles from it.

Produces ``graph_contract.pdf`` (vector) and ``graph_contract.png`` (raster).
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
FILL_CONCEPT = "#e8eef6"
FILL_SKILL = "#edf2ef"
FILL_MC = "#f4eaec"
FILL_CARD = "#fbfcfd"

C_PRQ = "#7f8fa0"
C_CROSS = "#b08a5a"
C_SKILL = "#4f7f63"
C_MC = "#a4515f"


def _box(ax, x, y, w, h, text, *, fill, edge=EDGE, fs=7.4, ls="-"):
    ax.add_patch(
        FancyBboxPatch(
            (x - w / 2, y - h / 2),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.10",
            linewidth=0.9,
            edgecolor=edge,
            facecolor=fill,
            linestyle=ls,
            zorder=3,
        )
    )
    ax.text(x, y, text, ha="center", va="center", fontsize=fs,
            color=INK, zorder=4, linespacing=1.35)


def _arrow(ax, p, q, *, color=EDGE, ls="-", lw=0.9, rad=0.0, shrink=13):
    ax.add_patch(
        FancyArrowPatch(
            p, q, arrowstyle="-|>", mutation_scale=8, linewidth=lw,
            color=color, linestyle=ls,
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=shrink, shrinkB=shrink, zorder=2,
        )
    )


def draw_graph(ax):
    ax.set_xlim(0, 10.9)
    ax.set_ylim(0.2, 10.5)
    ax.axis("off")

    pos = {
        "C1101": (5.1, 9.35),
        "C1102": (5.1, 7.75),
        "C1103": (2.85, 6.05),
        "C1104": (7.25, 6.05),
        "C1105": (2.85, 4.15),
        "C1106": (7.25, 3.35),
        "S1002": (9.35, 7.75),
        "MC03": (9.15, 4.35),
        "C1004": (1.02, 8.45),
    }
    label = {
        "C1101": "循环队列",
        "C1102": "取模运算",
        "C1103": "队空条件",
        "C1104": "队满条件",
        "C1105": "队列长度计算",
        "C1106": "循环队列的实现",
        "S1002": "取模计算\n（技能）",
        "MC03": "MC03\n判满条件",
        "C1004": "假溢出\n（U10）",
    }
    size = {
        "C1106": (2.25, 0.76),
        "C1105": (2.25, 0.76),
        "MC03": (2.20, 0.84),
        "S1002": (1.70, 0.80),
    }

    # session frame
    ax.add_patch(
        FancyBboxPatch(
            (1.55, 2.72), 9.15, 7.42,
            boxstyle="round,pad=0.06,rounding_size=0.18",
            linewidth=0.8, edgecolor="#c7d0d9", facecolor="none",
            linestyle=(0, (3, 3)), zorder=1,
        )
    )
    ax.text(10.55, 10.28, "U11 子图 $G_u$", fontsize=7.2, color=MUTED,
            style="italic", ha="right")

    for nid, (x, y) in pos.items():
        w, h = size.get(nid, (1.82, 0.72))
        if nid == "C1004":
            fill, ls, ec = PAPER, "--", "#b9c3cc"
        elif nid == "S1002":
            fill, ls, ec = FILL_SKILL, "-", "#a8bdb1"
        elif nid == "MC03":
            fill, ls, ec = FILL_MC, "-", "#c9a9b0"
        else:
            fill, ls, ec = FILL_CONCEPT, "-", "#a9bacd"
        _box(ax, x, y, w, h, label[nid], fill=fill, edge=ec, ls=ls,
             fs=6.2 if nid == "MC03" else (6.8 if nid == "S1002" else 7.4))

    for a, b in [
        ("C1101", "C1102"),
        ("C1102", "C1103"),
        ("C1102", "C1104"),
        ("C1103", "C1104"),
        ("C1102", "C1105"),
        ("C1104", "C1106"),
        ("C1105", "C1106"),
    ]:
        _arrow(ax, pos[a], pos[b], color=C_PRQ)

    _arrow(ax, (1.30, 8.95), (4.16, 9.38), color=C_CROSS, ls=(0, (4, 2)), rad=-0.18)
    _arrow(ax, pos["S1002"], pos["C1102"], color=C_SKILL, ls=(0, (1.6, 1.6)))
    _arrow(ax, pos["C1104"], pos["MC03"], color=C_MC, ls=(0, (4, 2)), rad=0.30)

    # legend, two rows, below the frame
    items = [
        ("prerequisites_for", C_PRQ, "-"),
        ("跨讲次先修", C_CROSS, (0, (4, 2))),
        ("implements", C_SKILL, (0, (1.6, 1.6))),
        ("addresses_misconception", C_MC, (0, (4, 2))),
    ]
    for i, (txt, col, ls) in enumerate(items):
        x0 = 1.62 + (i % 2) * 4.35
        y0 = 2.42 - (i // 2) * 0.42
        ax.plot([x0, x0 + 0.52], [y0, y0], color=col, lw=1.0, ls=ls,
                solid_capstyle="butt")
        ax.text(x0 + 0.64, y0, txt, fontsize=6.2, color=MUTED, va="center")


def draw_contract(ax):
    ax.set_xlim(0, 10.9)
    ax.set_ylim(0.2, 10.5)
    ax.axis("off")

    ax.add_patch(
        FancyBboxPatch(
            (0.22, 0.62), 10.45, 9.55,
            boxstyle="round,pad=0.06,rounding_size=0.18",
            linewidth=0.8, edgecolor="#c7d0d9", facecolor=FILL_CARD,
        )
    )
    ax.text(0.55, 9.78, "编译产物  $C(u)$ —— 生成与验收的同一份真值",
            fontsize=7.6, color=INK, fontweight="bold")

    rows = [
        ("$S_u$", "必需概念集\n（≥ 掌握）",
         "循环队列 · 取模运算 · 队空条件\n队满条件 · 队列长度计算 · 循环队列的实现",
         8.55, 1.60),
        ("$\\prec_u$", "讲解顺序\n（拓扑序）",
         "循环队列 → 取模运算 → {队空, 队满}\n→ {队列长度计算, 循环队列的实现}",
         6.55, 1.55),
        ("$M_u$", "必须纠正\n的误区",
         "MC03 判满条件是 rear == front\n→ 至少一页 layout = misconception",
         4.60, 1.55),
        ("$F_u$", "禁列词\n（本课程不讲）",
         "优先队列 · 单调队列 · 消息队列\n最短路径 · 拓扑排序",
         2.85, 1.30),
        ("$B_u$", "可简要回顾\n的兄弟讲次",
         "队列 · 队头与队尾 · 假溢出 · 链队列",
         1.58, 0.72),
        ("$k_u$", "页数预算", "7 页", 0.86, 0.44),
    ]

    for sym, tag, body, y, h in rows:
        ax.add_patch(
            FancyBboxPatch(
                (0.50, y - h / 2), 9.90, h,
                boxstyle="round,pad=0.02,rounding_size=0.10",
                linewidth=0.6, edgecolor="#dde3e9", facecolor=PAPER,
            )
        )
        ax.text(1.00, y, sym, fontsize=8.2, color="#3d5a80", ha="center",
                va="center", fontweight="bold")
        ax.text(1.85, y, tag, fontsize=5.9, color=MUTED, ha="left", va="center",
                linespacing=1.45)
        ax.text(4.55, y, body, fontsize=5.9, color=INK, ha="left", va="center",
                linespacing=1.7)


def main() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.6), facecolor=PAPER)
    draw_graph(axes[0])
    draw_contract(axes[1])
    fig.subplots_adjust(left=0.004, right=0.996, top=0.99, bottom=0.004, wspace=0.035)

    axes[0].text(0.01, -0.01, "(a)", transform=axes[0].transAxes,
                 fontsize=8, color=INK, fontweight="bold")
    axes[1].text(0.01, -0.01, "(b)", transform=axes[1].transAxes,
                 fontsize=8, color=INK, fontweight="bold")

    for ext in ("pdf", "png"):
        path = OUT / f"graph_contract.{ext}"
        fig.savefig(path, dpi=300, bbox_inches="tight", facecolor=PAPER)
        print(f"wrote {path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
