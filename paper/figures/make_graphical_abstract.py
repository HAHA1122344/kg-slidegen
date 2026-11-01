"""Generate the graphical abstract for the Knowledge-Based Systems submission.

Elsevier renders the graphical abstract in a 500 x 200 pixel window, so the
whole design is drawn on a canvas with exactly that 2.5:1 ratio and every font
is chosen to survive a 2.66x reduction (nothing below 12 pt on a 13.3 in wide
canvas, i.e. >= 9 px after scaling).

House rules from the Elsevier guidelines this file obeys:
  * 1328 x 531 px minimum at 300 dpi  -> we emit 3990 x 1596 px (same ratio).
  * Times / Arial / Courier / Symbol only  -> Arial, including math italics.
  * no "Graphical Abstract" heading and no text outside the image.
  * reads left to right, clear start and end.

Run:  python paper/figures/make_graphical_abstract.py
      python paper/figures/make_graphical_abstract.py --check   # layout audit

Outputs ``graphical_abstract.pdf`` (vector, preferred by the submission
system) and ``graphical_abstract.png`` (300 dpi raster preview).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

OUT = Path(__file__).resolve().parent

# Same palette as make_fig1.py, so the abstract and Figure 1 read as one family.
INK = "#1f2933"
MUTED = "#5c6b7a"
EDGE = "#8b9aa8"
PAPER = "#ffffff"
FILL_KG = "#e8eef6"
FILL_DERIVED = "#edf2ef"
FILL_MODEL = "#f7f0e5"
FILL_CHECK = "#f4eaec"
ACCENT = "#8c4a3f"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    # No mathtext anywhere: Elsevier allows Arial only, and matplotlib's custom
    # math fontset silently fell back to a serif face for $C(u)$.  Italic
    # identifiers are composed from ordinary Arial-italic text instead.
    "axes.unicode_minus": False,
    # Type 3 (matplotlib's default) is rejected by most production workflows;
    # embed real TrueType outlines instead.
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

W, H = 13.30, 5.32                 # exactly 2.5:1, the ratio ScienceDirect uses
ROW_Y, ROW_H = 3.36, 1.74          # pipeline band
ROW_C = ROW_Y + ROW_H / 2          # 4.23
LOOP_Y = 3.02                      # feedback path
RULE_Y, VAL_Y, LBL_Y, NOTE_Y = 2.72, 2.28, 1.84, 1.50
TAKE_Y = 0.72

BOXES = {                          # x0, width
    "kg": (0.26, 2.30),
    "contract": (3.48, 3.10),
    "llm": (7.50, 2.10),
    "deck": (10.52, 2.52),
}
GAP = 0.92                         # wide on purpose: the arrows are the story


def centre(key: str) -> float:
    x0, w = BOXES[key]
    return x0 + w / 2


def card(ax, key, fill, *, accent=False):
    x0, w = BOXES[key]
    ax.add_patch(
        FancyBboxPatch(
            (x0, ROW_Y), w, ROW_H,
            boxstyle="round,pad=0,rounding_size=0.09",
            linewidth=2.0 if accent else 1.1,
            edgecolor=ACCENT if accent else EDGE,
            facecolor=fill, zorder=2,
        )
    )


def badge(ax, key, n):
    """Step number pinned on the top-left corner: turns four cards into a sequence.

    It sits astride the border rather than inside the card, because the card
    interiors are already full of text at the sizes this figure needs.
    """
    x0, _ = BOXES[key]
    cx, cy = x0 + 0.05, ROW_Y + ROW_H - 0.05
    ax.add_patch(plt.Circle((cx, cy), 0.155, facecolor=PAPER,
                            edgecolor=EDGE, linewidth=1.0, zorder=7))
    label(ax, cx, cy - 0.005, str(n), 12, MUTED, weight="bold", zorder=8)


def label(ax, x, y, s, size, color=INK, *, weight="normal", style="normal",
          ha="center", va="center", zorder=6, **kw):
    return ax.text(x, y, s, fontsize=size, color=color, fontweight=weight,
                   fontstyle=style, ha=ha, va=va, zorder=zorder,
                   linespacing=1.35, **kw)


def arrow(ax, start, end, *, dashed=False, color=EDGE, lw=1.3, scale=14):
    ax.add_patch(
        FancyArrowPatch(
            start, end,
            arrowstyle="-|>", mutation_scale=scale,
            linewidth=lw, color=color,
            linestyle=(0, (3.2, 2.2)) if dashed else "solid",
            shrinkA=1, shrinkB=1, zorder=3,
        )
    )


def spans(ax, cx, y, parts, size, color=INK, weight="normal"):
    """One centred line made of alternating upright / italic runs.

    matplotlib cannot italicise part of a string without mathtext, and mathtext
    cannot use Arial here, so the pieces are laid out by their measured advance
    widths.  Trailing spaces count towards the advance, which is what keeps the
    gap between ``One contract`` and ``C(u)`` correct.
    """
    fig = ax.figure
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    made = []
    for text, italic in parts:
        t = ax.text(cx, y, text, fontsize=size, color=color, fontweight=weight,
                    fontstyle="italic" if italic else "normal",
                    ha="left", va="center", zorder=6)
        made.append((t, t.get_window_extent(renderer=r).width))
    per_unit = ax.transData.transform((1, 0))[0] - ax.transData.transform((0, 0))[0]
    x = cx - (sum(w for _, w in made) / per_unit) / 2
    for t, w in made:
        t.set_position((x, y))
        x += w / per_unit


def graph_glyph(ax, cx, cy):
    """Four-node graph: the only stage whose input is a structure, not text."""
    nodes = [(cx - 0.34, cy), (cx, cy - 0.16), (cx, cy + 0.18), (cx + 0.34, cy)]
    for a, b in ((0, 1), (0, 2), (1, 3), (2, 3)):
        ax.plot([nodes[a][0], nodes[b][0]], [nodes[a][1], nodes[b][1]],
                color=EDGE, linewidth=1.1, zorder=3, solid_capstyle="round")
    for i, (nx, ny) in enumerate(nodes):
        ax.plot([nx], [ny], marker="o", markersize=6.5,
                color=ACCENT if i == 1 else MUTED, zorder=4,
                markeredgecolor=PAPER, markeredgewidth=1.0)


def slide_stack(ax, cx, cy):
    """Three offset rectangles: a deck, not a screenshot."""
    w, h = 0.52, 0.32
    for i, (dx, dy) in enumerate(((0.10, 0.14), (0.05, 0.07), (0.0, 0.0))):
        ax.add_patch(
            Rectangle((cx - w / 2 + dx, cy - h / 2 + dy), w, h,
                      linewidth=1.0, edgecolor=EDGE,
                      facecolor=PAPER if i == 2 else FILL_CHECK,
                      zorder=3 + i)
        )


def build() -> None:
    fig = plt.figure(figsize=(W, H), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor(PAPER)

    # ---------------------------------------------------------- pipeline
    card(ax, "kg", FILL_KG)
    graph_glyph(ax, centre("kg"), 4.76)
    label(ax, centre("kg"), 4.24, "Curriculum graph", 18, weight="bold")
    label(ax, centre("kg"), 3.92, "34 concepts \u00b7 75 edges", 12.5, MUTED)
    label(ax, centre("kg"), 3.68, "4 misconceptions", 12.5, MUTED)

    card(ax, "contract", FILL_DERIVED, accent=True)
    spans(ax, centre("contract"), 4.66,
          [("One contract  ", False), ("C(u)", True)], 21, weight="bold")
    label(ax, centre("contract"), 4.22, "\u2192  writes the prompt", 16)
    label(ax, centre("contract"), 3.90, "\u2192  checks the result", 16)
    label(ax, centre("contract"), 3.58, "order, coverage, misconceptions", 12, MUTED)

    card(ax, "llm", FILL_MODEL)
    label(ax, centre("llm"), 4.48, "DeepSeek", 19, weight="bold")
    label(ax, centre("llm"), 4.10, "JSON per slide", 12.5, MUTED)
    label(ax, centre("llm"), 3.86, "25 pages", 12.5, MUTED)

    card(ax, "deck", FILL_CHECK)
    slide_stack(ax, centre("deck"), 4.74)
    label(ax, centre("deck"), 4.28, "Editable .pptx", 17.5, weight="bold")
    label(ax, centre("deck"), 3.96, "all-native shapes", 12.5, MUTED)
    label(ax, centre("deck"), 3.72, "no rasterised text", 12.5, MUTED)

    for left, right, verb in (("kg", "contract", "compile"),
                              ("contract", "llm", "prompt"),
                              ("llm", "deck", "render")):
        x1 = BOXES[left][0] + BOXES[left][1]
        x2 = BOXES[right][0]
        arrow(ax, (x1 + 0.03, ROW_C), (x2 - 0.03, ROW_C),
              color=MUTED, lw=1.8, scale=19)
        label(ax, (x1 + x2) / 2, ROW_C + 0.30, verb, 13.5, MUTED, style="italic")

    for n, key in enumerate(("kg", "contract", "llm", "deck"), start=1):
        badge(ax, key, n)

    # ------------------------------- second role: the same contract grades
    # One source, two roles. The solid path feeds the prompt; this bypass feeds
    # the acceptance check, routed below the model so it does not imply that
    # grading happens before generation.
    dx = centre("deck")
    cx = centre("contract")
    ax.plot([cx, cx], [ROW_Y, LOOP_Y], color=ACCENT, linewidth=1.4,
            linestyle=(0, (3.4, 2.4)), zorder=1)
    ax.plot([cx, dx], [LOOP_Y, LOOP_Y], color=ACCENT, linewidth=1.4,
            linestyle=(0, (3.4, 2.4)), zorder=1)
    arrow(ax, (dx, LOOP_Y), (dx, ROW_Y - 0.02), dashed=True, color=ACCENT,
          lw=1.4, scale=17)
    label(ax, (cx + dx) / 2, LOOP_Y, "the deck is graded against the same contract",
          12.5, ACCENT, bbox=dict(facecolor=PAPER, edgecolor="none", pad=3.0))

    # ------------------------------------------------------------ results
    # One hairline separates "what we built" from "what it bought"; three short
    # rules above the numbers read as stray strokes at 500 px wide.
    ax.plot([0.28, W - 0.28], [RULE_Y, RULE_Y], color="#c6ced6", linewidth=0.9, zorder=2)
    tiles = [
        ("0.61\u20130.70 \u2192 0.98", "coverage of required concepts",
         "a length-matched placebo gains nothing"),
        ("1.000 vs 0.556", "misconceptions addressed", "s.d. 0.000 vs 0.527"),
        ("no reliable gain", "prerequisite ordering", "seven metric defects corrected first"),
    ]
    for i, (val, lab, note) in enumerate(tiles):
        x = W * (2 * i + 1) / 6
        label(ax, x, VAL_Y, val, 25, weight="bold")
        label(ax, x, LBL_Y, lab, 15)
        label(ax, x, NOTE_Y, note, 13, MUTED)

    label(ax, W / 2, TAKE_Y,
          "Course-level knowledge is not in the weights; the compiled graph supplies it.",
          18, INK, style="italic")

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    for suffix, dpi in (("pdf", None), ("png", 300)):
        path = OUT / f"graphical_abstract.{suffix}"
        fig.savefig(path, dpi=dpi, facecolor=PAPER)
        print(f"wrote {path}")
    print(f"png pixels: {round(W * 300)} x {round(H * 300)}")

    # Keep the submission bundle self-contained: paper/latex/ is what gets
    # zipped for the journal, so it needs the same vector file.
    bundle = OUT.parent / "latex"
    if bundle.is_dir():
        (bundle / "graphical_abstract.pdf").write_bytes(
            (OUT / "graphical_abstract.pdf").read_bytes()
        )
        print(f"copied -> {bundle / 'graphical_abstract.pdf'}")

    audit(fig, ax)
    plt.close(fig)


def audit(fig, ax) -> None:
    """Fail loudly on text that leaves the canvas or collides with other text.

    At 500 x 200 nothing can be nudged by eye, and a clipped word is invisible
    at authoring size but obvious in the ScienceDirect thumbnail.
    """
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    size = fig.canvas.get_width_height()
    bad = 0
    boxes = []
    for t in ax.texts:
        bb = t.get_window_extent(renderer=r)
        s = t.get_text().replace("\n", " ")[:38]
        if bb.x0 < 1 or bb.y0 < 1 or bb.x1 > size[0] - 1 or bb.y1 > size[1] - 1:
            print(f"  OUT OF CANVAS: {s!r}")
            bad += 1
        boxes.append((bb, s))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, sa = boxes[i]
            b, sb = boxes[j]
            # Shrink by a pixel: the runs of one `spans()` line abut exactly,
            # which is correct typesetting but reads as an overlap.
            if a.padded(-1).overlaps(b.padded(-1)):
                print(f"  OVERLAP: {sa!r} <-> {sb!r}")
                bad += 1
    print("layout audit:", "clean" if bad == 0 else f"{bad} problem(s)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="run the layout audit (always on; kept for clarity)")
    ap.parse_args()
    build()


if __name__ == "__main__":
    main()
