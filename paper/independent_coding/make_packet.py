#!/usr/bin/env python3
"""Build the blind packet for an independent second coder.

Why this exists
---------------
The seven metrics are written by the same person who wrote the contract, so a
reviewer is entitled to ask whether an independent coder, using the same rubric,
reproduces the ordering. Section 7.5 concedes that no such coder exists. This
script makes the missing check cheap: it copies a stratified 20% subsample of the
54 main-grid decks under opaque identifiers, emits a blank rating sheet, and keeps
the mapping in a separate key file that is not given to the coder.

Usage
    python paper/independent_coding/make_packet.py            # build the packet
    python paper/independent_coding/make_packet.py --share 6  # stop after 6 decks

The packet lands in paper/independent_coding/packet/:
    decks/D01.pptx ...   opaque copies, no condition in the name
    rubric_blank.csv     one row per deck, empty ratings
    key.csv              deck -> (condition, session, run) -- NOT for the coder
    README.md            the instructions to send with the packet

A second coder fills rubric_blank.csv, returns it, and
``agreement.py`` reports how far the two coders agree.
"""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "packet"
GRID = ROOT / "outputs" / "main_v1"  # the 54-run main grid: 6 conditions x 3 sessions x 3 runs

CONDITIONS = ["full", "rag_mc", "rag", "placebo", "cot", "zero_shot"]
TAKE_PER_CONDITION = 2  # 12 decks from 54 runs = 22%, stratified by condition

ITEMS = [
    "Q1_Syllabus_Coverage",
    "Q2_Misconception_Correction",
    "Q3_Pedagogical_Logic",
    "Q4_Content_Accuracy",
    "Q5_Classroom_Readiness",
]


def runs_for(condition: str) -> list[Path]:
    """Every deck of one condition in the main grid, in a stable order."""
    return sorted(GRID.glob(f"*__{condition}__*.pptx"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--share", type=int, default=len(CONDITIONS) * TAKE_PER_CONDITION,
                    help="number of decks to put in the packet")
    ap.add_argument("--seed", type=int, default=20261105)
    args = ap.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "decks").mkdir(parents=True)

    chosen: list[tuple[Path, str, str, str]] = []
    for cond in CONDITIONS:
        pool = runs_for(cond)
        if not pool:
            raise SystemExit(f"no decks for condition {cond} under {GRID}")
        # spread the pick over the pool instead of taking the first two runs
        step = max(1, len(pool) // TAKE_PER_CONDITION)
        for i in range(TAKE_PER_CONDITION):
            deck = pool[(i * step) % len(pool)]
            session, _, run = deck.stem.split("__")
            chosen.append((deck, cond, session, run))

    chosen = chosen[: args.share]

    key_rows = []
    for i, (deck, cond, session, run) in enumerate(chosen, start=1):
        opaque = f"D{i:02d}"
        shutil.copy2(deck, OUT / "decks" / f"{opaque}{deck.suffix}")
        key_rows.append({"Deck_ID": opaque, "Condition": cond,
                         "Session_ID": session, "Run": run,
                         "Source": str(deck.relative_to(ROOT))})

    with (OUT / "key.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(key_rows[0]))
        w.writeheader()
        w.writerows(key_rows)

    with (OUT / "rubric_blank.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Deck_ID", "Coder_ID", *ITEMS, "Overall_Score", "Notes"])
        for row in key_rows:
            w.writerow([row["Deck_ID"], "", "", "", "", "", "", "", ""])

    (OUT / "README.md").write_text(PROTOCOL.format(n=len(key_rows)), encoding="utf-8")

    print(f"packet ready: {len(key_rows)} decks -> {OUT}")
    print(f"  send : decks/, rubric_blank.csv, README.md")
    print(f"  keep : key.csv (it names the conditions)")


PROTOCOL = """# Blind coding packet

You are asked to rate {n} slide decks. You do not need to know how they were
produced, and the packet deliberately does not say.

## What to do

1. Open each deck in `decks/` (PowerPoint, Keynote or LibreOffice all work).
2. Read it as a teacher of this course would, at the pace you would use to
   decide whether to teach from it.
3. Score five items on a 1-5 scale, in `rubric_blank.csv`, one row per deck.
   Write your initials in `Coder_ID` on every row.

Use the whole scale. There is no expected distribution and no penalty for
giving a deck a low score.

| Item | 1 (absent) | 3 (adequate) | 5 (fully adequate) |
|---|---|---|---|
| Syllabus coverage | the session's required concepts are largely missing | most are present, some only named | every required concept is taught, with a definition and an example |
| Misconception correction | the misconception this class holds is not addressed | mentioned once, without a correction | named, corrected, and the failure mode is shown |
| Pedagogical logic | the order of ideas would confuse a student | roughly follows the textbook order | each idea is prepared by the previous one |
| Content accuracy | statements are wrong | correct but thin | correct, precise, and consistent with the textbook |
| Classroom readiness | you would have to rewrite it before teaching | usable with editing | usable as it stands |

`Overall_Score` is your own holistic judgement, not an average you must compute.

## Two rules

- Score independently. Do not discuss the decks with anyone before you finish,
  and do not compare them with each other while scoring.
- If a deck is unreadable or broken, say so in `Notes` and leave the scores
  blank rather than guessing.

## What happens with the result

Your ratings are compared with the ratings of the original reviewer and with an
automatic metric. The comparison is reported as agreement (ICC and a weighted
kappa), not as a contest: disagreement is the interesting part, because it says
where the rubric is ambiguous.
"""


if __name__ == "__main__":
    main()
