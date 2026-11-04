# Experimental protocol (reproducible record)

This file records where every number in the paper comes from. If you change the code,
re-run the experiments and update this file; otherwise the paper and the repository will
disagree — and if a reviewer clones the repository and cannot reproduce the numbers, nothing
else matters.

## 1. Fixed conditions

| Item | Value |
| --- | --- |
| Model | `deepseek-v4-flash` |
| temperature | 0.3 |
| max_tokens | 16000 |
| Thinking mode | default (the model performs one internal reasoning round; `reasoning_tokens` is logged separately) |
| JSON mode | on, `response_format={"type":"json_object"}` |
| Lectures | U10 concepts and false overflow of queues / U11 circular queues / U12 linked queues and the BFS lead-in |
| Page count | given by the graph's `slide_budget` (6 / 7 / 6) |
| Resampling | 3 runs per cell in the main table, 2 in the ablations |

**Why the page count is fixed rather than left to the model**: page count is part of the
course contract; a teacher lays out the pages against the class hours. Releasing it would
make coverage meaningless — more pages naturally cover more, and the comparison degenerates
into a comparison of page counts.

## 2. The six contrasts

The information each arm receives is strictly nested, stripping structure one item at a time:

| Condition | Course/lecture name | Page count | Concept names + definitions | Topological order | Misconceptions | Forbidden terms | Prompt length (U11) |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| `full` | ✓ | ✓ | ✓ | ✓ | ✓ (own block + layout requirement) | ✓ | 1997 |
| `rag_mc` | ✓ | ✓ | ✓ | ✗ | ✓ (flat text) | ✗ | 1122 |
| `rag` | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | 997 |
| `placebo` | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | 2195 |
| `cot` | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | 625 |
| `zero_shot` | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | 585 |

`rag` and `zero_shot` differ only in the textbook excerpts, so their difference measures the
contribution of **content retrieval**; `full` and `rag` differ only in structure (order,
misconceptions, forbidden terms), so their difference measures the contribution of
**structural constraint**. This design lets each layer's gain be attributed separately
instead of making the blanket claim that "our prompt is better".

The `cot` arm additionally asks the model to state its positioning in each page's `notes`
before writing the content — it is the upper bound of what prompt engineering alone can do.

**`rag_mc` is a control built specifically for the misconception conclusion**, to pre-empt an
objection that will certainly be raised: "you only win on the misconception metric because
you wrote the misconceptions into the prompt, and that is prompting, not a knowledge graph."
This arm hands the model the same misconception text as a flat excerpt, but gives no order,
no layout requirement and no must-cover list. If `full` still wins reliably on the
misconception metric, the gain comes from **being structured enough to constrain the page**,
not from the text appearing in the prompt.

**`placebo` is a control built specifically for the "longer prompt" alternative
explanation**: the prompt is padded to the length of `full` (in practice 1–16% longer), but
the padding is generic courseware-writing advice unrelated to the course. If the advantage of
`full` came from prompt length, this arm should catch up; measured, it does not. Note that
this arm's prompt is **longer than full's**, so it is a conservative control: `full` wins with
a shorter prompt.

## 3. The three ablations

The complete contract and rule wording of `full` are kept; exactly one data block is removed:

| Condition | Removed content | Metric expected to move |
| --- | --- | --- |
| `no_order` | the `teaching order` block + rule 3 | `prerequisite_violation` |
| `no_misconception` | the `misconceptions that must be corrected` block + rule 5 | `misconception_coverage` |
| `no_forbidden` | the `concepts that must not be introduced` block + rule 6 | `oog_rate` |

Deleting the rule text along with the block is essential: if only the data block goes and
the rule "you must follow the given order" stays, the model will guess an order and the
ablation is no longer clean. The test `test_ablation_prompt_drops_exactly_one_block` guards
this.

**How to read it (Table 5 in the paper)**: an ablation is not a second set of condition
means but an attribution — remove one block, re-measure all four metrics, and the value of a
block is the displacement of the metric it was supposed to govern: the misconception slot
−0.833 (with coverage −0.056 alongside), the forbidden-term list +0.083 on the off-graph
rate with everything else unmoved, the ordering block −0.032 but a no-op (see below).
`python paper/tables.py --latex` generates `paper/latex/attribution.tex` from the same
`results.csv`, with a side-effect threshold of 0.04; moves below it are not listed, because
they are sampling noise rather than attribution.

## 4. Metric definitions

| Metric | Definition | Known bias and how it is handled |
| --- | --- | --- |
| `coverage_rate` | required concepts that are "taught" | body pages only; concepts merely listed on the title, objectives or summary page do not count as taught. Matching uses name ∪ graph aliases, so the `full` arm is not favoured for copying the original names |
| `oog_rate` | (out-of-graph IDs + forbidden-term hits) / (covered + out-of-graph) | only IDs in the graph's own format (`^[A-Z]{1,3}\d{2,4}$`) that do not exist are counted; a slug the model invents (`queue-def`) belongs to another namespace and is not judged off-topic |
| `background_rate` | **characters** spent on sibling-lecture concepts / total characters | characters, not concept count: one comparison slide naming three sibling concepts is normal teaching |
| `prerequisite_violation` | concept pairs violating the topological order / total concept pairs | see "How ordering is judged" below |
| `misconception_coverage` | misconceptions corrected / misconceptions attached to the lecture | three-way decision: structural anchor → English identifier overlap → Chinese character bigram (threshold 0.35) |
| `editability` | native editable shapes / all shapes | determined by the `python-pptx` renderer; all-native is 1.0 |

### How ordering is judged

This is the part that changed the most and breaks most easily, so it gets its own section.

1. **The model's self-reported `concept_ids` are ignored.** The three baselines are never told
   the field exists; scoring on self-reports would give a completely blank answer a violation
   rate of zero — treating a non-answer as a perfect score.
2. **Title, objectives and summary pages are excluded.** By definition these list every
   concept, so including them flattens the first-occurrence position of all concepts and lets
   dictionary order, not teaching order, decide the ranking. Measured, this alone created
   three spurious violations.
3. **Position is fixed by "named in the title", not by first mention.** What a page teaches is
   what its title names; a forward reference in the body ("the modulo is the key to
   implementing a circular queue") does not mean the page teaches that concept. Measured,
   this created two spurious violations.
4. **Within a page, order by literal offset**, then take the total order by
   `(page index, offset)`.
5. **Matching uses name ∪ aliases**, the same table as coverage, so no condition is favoured
   for copying the original names.

### One trap in Chinese matching

`队列` also matches inside `循环队列`. All text counts use a **line-by-line** net occurrence
count (raw count − occurrences covered by a longer term on that same line). Doing the
subtraction per line rather than over the whole document is essential: otherwise a
standalone `队列` on page 2 is cancelled by `顺序队列` on page 4 and the concept is judged
"never taught". This bug really happened.

## 5. Limitations of the measurement that must be acknowledged

1. **The coverage of `full` is naturally close to 1.0.** The prompt contains that concept
   list, so the model can simply copy it. A single absolute value does not demonstrate
   superiority; what is comparable is the **variance across resamplings** and the gaps to the
   other conditions.
2. **The six metrics measure contract compliance, not teaching quality.** Whether a lecture
   is any good, whether examples fit, whether the board-work has the right rhythm — none of
   this is measured. A teacher blind review supplements it (§6), but 10 decks × 3 raters
   supports an agreement check only, not full coverage of teaching dimensions, and the metrics
   must not be passed off as teaching quality.
3. **`misconception_coverage` is structurally unfavourable to the baselines**, because they
   are never told the misconceptions. That is not a defect but the conclusion itself:
   course-level misconception knowledge is not in the model's weights and has to be supplied
   by a knowledge base. The `rag_mc` control is the upper-bound contrast built for exactly
   this — it shows that "given the text" and "given the structure" are not the same thing.
4. **`oog_rate` is almost always 0 on the existing data**, because the three layers of
   protection (must-cover list, forbidden-term list, background cap) have already closed off
   drifting and the model has no opportunity to wander. The metric behaves more like a safety
   net than a source of discrimination.
5. **The sample is small** (3 lectures × 3 runs). Statistical tests can only be descriptive;
   p-values must not be reported as strong evidence.

## 6. Teacher blind review

- **Data**: `paper/human_eval.csv`, one row = one deck × one rater; 10 decks × 3 raters = 30
  rows
- **Distribution**: `full` 3 decks / `rag_mc` 3 / `rag` 3 / `placebo` 1 (each rated by 3
  raters)
- **Dimensions**: Q1 syllabus coverage, Q2 misconception correction, Q3 teaching logic,
  Q4 content accuracy, Q5 classroom usability, on a 1–5 scale
- **Total**: `Overall_Score` is the **unweighted mean** of the five items; the script verifies
  this, and the current maximum deviation is 0.0000
- **Reliability**: ICC(2,3) (two-way random, absolute agreement), total **0.92**; by item
  Q2 0.91, Q5 0.91, Q1 0.80, Q3 0.53, Q4 0.00. Q4's zero is **structural**: every condition
  scores above 4.0 and between-deck variance is indistinguishable from rating noise
  (F(9,18) = 1.00), so it is not a case of raters disagreeing
- **No significance test**: with 3 decks against 3, the smallest two-sided permutation p
  under complete separation is 0.10, so the review is read as agreeing with the automatic
  metrics, not as independent confirmation
- **Against the automatic metrics**: Q2 normalised to [0,1] gives 0.97 / 0.56 / 0.42 / 0.28
  (full / rag_mc / placebo / rag) against automatic values of 1.000 / 0.556 / 0.333 / 0.222
  — **identical ranks, largest gap 0.09**

```bash
python paper/human_eval.py          # descriptives + ICC + bootstrap intervals
python paper/human_eval.py --latex  # emit the LaTeX table for the paper
```

## 7. Two robustness checks: measurement conventions and code blocks

A reviewer objected that counting coverage on body pages only would systematically penalise
baselines that put definitions on the title page. That kind of objection cannot be answered
by argument, only by recomputation:

```bash
python paper/coverage_sensitivity.py            # three front-matter conventions + no alias matching
python paper/code_check.py                      # ast.parse every block
```

| Convention | `full` | `rag_mc` | `placebo` | `rag` | `zero_shot` | `cot` | Runs affected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Body pages only (the paper's convention) | 0.981 | 0.698 | 0.675 | 0.659 | 0.643 | 0.614 | — |
| Title page included | 1.000 | 0.698 | 0.675 | 0.659 | 0.643 | 0.632 | 2 / 54 |
| All pages included | 1.000 | 0.772 | 0.728 | 0.749 | 0.643 | 0.632 | ranking ρ = 0.94 |
| Exact names only, no aliases | 0.963 | 0.389 | 0.325 | 0.373 | 0.357 | 0.370 | 31 / 54 |

Conclusion: relaxing to the title page moves only two runs (U10/full/r3, U10/cot/r2) and
leaves the condition ordering untouched, while `full − rag_mc` rises from +0.283 to +0.302;
dropping alias matching instead pushes the baselines down to 0.33–0.39 while `full` falls
only to 0.963 (a gap of +0.574), which shows alias matching is **tightening** the result and
that the paper's +0.283 is a lower bound.

Code blocks: 54 runs contain 117 blocks, all of which pass `ast.parse` (every condition
scores 1.00), so the criterion is saturated and cannot discriminate. `full` has 28 blocks
(48% of its pages) and the baselines 16–19 (27%–33%). "It runs" therefore needs a
**behavioural** test to have any discriminative power. `paper/behavior_check.py` does a
bounded version: after removing `__main__` demo sections, blocks run in a clean namespace
against four behaviour classes (FIFO, empty, full, survival); 37 of 117 blocks are testable
and 36 pass. The paper states this explicitly in §7.6 as an **upper bound** rather than a
metric — `full`'s 8/9 and 28/28 are not evidence.

## 7b. Cross-model replication (second backbone)

Same prompts, same lectures, same metrics, one model from another vendor — to answer whether
the effect of structure is an artefact of prompt tuning for one model. This is not a
"which model is better" comparison:

| Item | DeepSeek (main experiment) | Kimi (replication) |
| --- | --- | --- |
| Model | `deepseek-v4-flash` | `kimi-k3` |
| temperature | 0.3 | **1.0 (pinned by the vendor; passing 0.3 returns 400)** |
| max_tokens | 16000 | 16000 |
| Prompts | identical (`_build_prompt` is shared) | identical |
| Cells | 6 conditions × 3 lectures × 3 runs = 54 | same |
| Output directory | `outputs/main_v1` | `outputs/bench_kimi` |

The differing temperature is the most attackable point in this replication, so it is pinned
explicitly through `ProviderPreset.fixed_temperature` in `LLMConfig`, every row of
`results.csv` records `model` and `temperature`, and the unit test
`test_vendor_pinned_temperature_is_applied` locks it down. Within each backbone the
conditions are identical, so **within-backbone contrasts are comparable and between-backbone
absolute values are not** — the table is used only to ask whether the sign of
`full − rag_mc` replicates, never to compare means across columns.

```bash
export MOONSHOT_API_KEY=sk-xxxx
python -m kgslide.bench --provider kimi --units U10,U11,U12 \
  --modes full,rag_mc,placebo,zero_shot --repeat 2 \
  --out outputs/bench_kimi --skip-existing
python paper/tables.py --cross outputs/bench_kimi   # writes paper/latex/cross_model.tex
```

**What was actually run (2026-11-03)**: the account's concurrency limit is 1 (three
concurrent processes returned 429 to each other), so the run was made **serial**; `rag` and
`cot` were not re-run on the second backbone (they carry no conclusion, at about 7 minutes per
cell), giving 4 conditions × 3 lectures × 2 runs = 24 cells, of which `U12/zero_shot#2` is
missing because the account quota ran out. The gap is recorded as it stands (`n=5`) and was
not fabricated.

| Metric | DeepSeek V4 | Kimi K3 |
| --- | --- | --- |
| Misconception coverage `full → rag_mc` | 1.000 → 0.556 (−0.444) | 1.000 → 0.667 (−0.333) |
| Coverage `full → rag_mc` | 0.981 → 0.698 (−0.283) | 1.000 → 0.734 (−0.266) |
| SD of `full`'s misconception coverage | 0.000 (9 of 9 at 1.000) | 0.000 (6 of 6 at 1.000) |
| SD of `rag_mc`'s misconception coverage | 0.527 | 0.516 |
| Pass rate `full` vs `rag_mc` | 67% vs 22% | 67% vs 17% |

The conclusion as written in §5.5: **the sign replicates on both backbones, the effect size
shrinks** (0.444 → 0.333), and on U11 all four Kimi conditions score 1.000, so that lecture
contributes no contrast on the second backbone. Variance behaviour replicates more stably
than means, which is direct support for the paper's claim about reliability rather than
average quality.

## 7c. Second course (C++ Programming, chapter 4, arrays)

### Why it exists

All the evidence in the first draft came from one course (Python data structures, three
lectures). A reviewer is right to be wary of "one course + one backbone + one of the core
constraint dimensions (ordering) coming out null": that combination cannot distinguish "the
contract works" from "this teacher's course happens to work this way". The second course is
not about enlarging the sample; it **changes the knowledge domain, the programming language
and the backbone** to see whether the direction of the two claim-bearing contrasts survives.

### Where the graph comes from (and how it differs — this is stated in the paper)

`data/build_cpp_m4.py` generates `data/kg_cpp_m4.json` from `第4章 数组.docx` (class 4 of the
2024 Animation Production Technology intake, week 2, session 5, 4 class hours): 26 nodes /
51 edges, `validate()` reports zero issues.

There is one difference, spelled out in the paper: **the misconceptions in the first course
are backed by exam error rates, whereas the misconceptions in the second course come from the
lesson plan's own "teaching priorities and difficulties" and "teaching reflection" — they are
difficulties the teacher recorded, not measured frequencies.** The three misconception nodes
are MC41 (indices start at 1), MC42 (character arrays need not worry about `'\0'`) and MC43
(array arguments are passed by value) — all extracted from the lesson plan, none invented.

One engineering detail worth noting: `UnitConstraints.language` injects the course language
into the prompt's JSON spec (`json_spec(code_lang)`). Without it, a C++ course is asked for
Python code, and the result is a **silent mix-up** — no error is raised, the code blocks are
simply in the wrong language.

### Design

2 lectures (U41 one-dimensional arrays, U42 character arrays and parameter passing) ×
3 conditions (`full`, `rag_mc`, `zero_shot`) × 2 resamplings = 12 cells. The backbone is
`agnes-2.5-flash` (`https://apihub.agnes-ai.com/v1`, temperature 0.3); the backbone was
switched because the primary keys were out of balance that day (DeepSeek 402, Moonshot 429).
That substitution is itself a **joint replacement of course and backbone**, and the paper says
so plainly and states that these magnitudes are not read against the main table.

### Results

| Metric | `full` | `rag_mc` | `zero_shot` |
| --- | --- | --- | --- |
| Coverage | 0.800 (0.163) | 0.600 (0.231) | 0.350 (0.191) |
| Off-graph content | 0.000 (0.000) | 0.000 (0.000) | 0.125 (0.250) |
| Order violation | 0.042 (0.083) | 0.017 (0.033) | 0.042 (0.083) |
| Misconception coverage | 0.625 (0.479) | 0.375 (0.479) | 0.000 (0.000) |

Three readings:

1. **The direction replicates.** Coverage +0.450 against zero-shot and +0.200 against the
   same-text control; misconceptions +0.625 / +0.250; the off-graph pattern of the first
   course recurs (zero-shot introduces content from later chapters, the contract does not).
   Both claim-bearing contrasts have the same sign on another course, another language and
   another backbone.
2. **The reliability does not replicate.** The misconception slot was 1.000 ± 0.000 in the
   first course and is 0.625 ± 0.479 here — filled in two runs out of four, with the
   same-text control just as dispersed. So reliability is not an intrinsic property of the
   contract but a **joint property of representation × backbone**. That sentence went into
   §6.2, and it is why the earlier unconditional claim that "the contract gets the slot
   filled every time" became a conditional one.
3. **Ordering is still the boundary.** `full` 0.042 = `zero_shot` 0.042, `rag_mc` 0.017: no
   contrast. This is the second independent reading of the boundary predicted in §1.5 — on a
   course whose textbook is equally authoritative on ordering, the dimension still fails to
   separate the conditions.

Two explanations are recorded and neither is adopted, because the design cannot separate them:
the backbone is weaker at the task (zero-shot coverage 0.35 against 0.64 in the first course,
and it is the only condition that introduces off-graph content), and the misconceptions are
recorded difficulties rather than measured frequencies (the prompt says "students often get
this wrong", not "how often").

## 7d. The separation run: splitting "the course changed" from "the backbone changed"

### Why it had to be added

The second course in §7c changed the course, the language, the backbone and the endpoint all
at once. The result is that "the variance of the misconception slot did not replicate", but
that design **cannot say** whether the cause lies in the course or in the model — a reviewer
will certainly ask, and "two factors moved together" is usually judged a dirty replication
rather than an honest boundary report.

### Design

Take the first course **exactly as it stands** (same graph `kg_pyds_m4.json`, same prompt,
same validator, same metric code) and move it to the second course's backbone,
`agnes-2.5-flash`:

```bash
PYTHONPATH=src python -m kgslide.bench --provider agnes \
  --kg data/kg_pyds_m4.json --units U10,U11,U12 \
  --modes full,rag_mc,zero_shot --repeat 2 --out outputs/bench_py_agnes
```

18 cells, about 8 minutes. Only the endpoint changed.

### Results

| Backbone | Course | n(full) | Δ coverage (full−rag_mc) | Δ misconception | full's misconception |
| --- | --- | :-: | :-: | :-: | :-: |
| DeepSeek V4 | Python | 9 | +0.283 | +0.444 | 1.000 (0.000) |
| Kimi K3 | Python | 6 | +0.266 | +0.333 | 1.000 (0.000) |
| agnes-2.5-flash | Python | 6 | +0.052 | **+0.000** | **0.833 (0.408)** |
| agnes-2.5-flash | C++ | 4 | +0.200 | +0.250 | 0.625 (0.479) |

In the first three rows the course, graph, prompt, validator and metric code are all fixed and
only the endpoint varies. In row 3 the misconception slot's advantage **goes to zero**, and
`full`'s dispersion moves from 0.000 to 0.408 — the same phenomenon seen on the second course.
Therefore: **the precondition sits with the model, not with the course.** The failure of the
second course is not a peculiarity of that course; it is this backbone's behaviour observed
once more on a different syllabus.

Two details that cannot be omitted:

1. **The forbidden-term list still binds on the same backbone**: off-graph 0.097 (`rag_mc`) →
   0.000 (`full`), matching the first course's pattern on DeepSeek. So this backbone is not
   "disobedient to structure"; it **will not fill a required page type**. "The model decides
   everything" would be an overgeneralisation.
2. **The coverage advantage over the same-text control falls to +0.052 in this row** (against
   zero-shot it is still +0.401). That is, on this backbone, laying the same misconception text
   in front of the model already comes close to the contract. This is a real boundary of the
   method: the contract supplies a capability the model lacks, and when the model reads
   carefully enough by itself, structure buys little on coverage.

Two cells (r1) triggered a real bug: the model wrote one slide as a bare string, the renderer
crashed on `.get()`, and all 18 cells were lost along with the CSV. Fixed:
`renderer.render` degrades a non-dict slide to a title-only page, `validator.evaluate`
normalises at the entry point, and `bench` wraps rendering and scoring in try/except so one bad
cell no longer takes down the whole table.

## 8. Repair loop

The main table reports a pass rate, not a first-pass pass rate by accident: nothing acted on
the validator's findings. `paper/repair_loop.py` adds the missing step and is run on stored
payloads, so no new condition enters any comparison.

**Policy.** For a run with an error-level finding, append the validator's error findings to the
same condition prompt and regenerate the whole deck; up to `--rounds` attempts (3 used). A run
that passed first time is untouched, so the repaired count has the same denominator as the
first-pass count. `validator.repair_instruction` renders the findings, and lists **only**
error-level ones: warnings (out-of-graph, missed misconception, background overuse) do not fail
a run, so repairing them would hold the second attempt to a stricter bar than the first.

**Why only `full`.** The feedback names the concepts a deck missed. For `full` that list is
already in the prompt, so the finding restates a requirement instead of adding one. For
`zero_shot` or `rag` the same sentence hands over the syllabus those conditions exist to lack,
and the repaired baseline is no longer a baseline. Whether a repair loop is fair is a property
of the condition, not of the loop — this is the reason the script refuses to be pointed at the
baselines for a headline number.

**Result (agnes-2.5-flash, the row-3 cell of §7d).** Six runs, first-pass 4/6. Of the two
failures: the one with `MISSING_CONCEPT` was fixed in a single round (the feedback named
`C1106 循环队列的实现`; the model added the page) and the other, with `PREREQ_VIOLATION`, was not
fixed in three (violation rate 0.048 → 0.048 → 0.381 — worse on the third attempt). Four model
calls for six runs, mean coverage 0.972 → 1.000.

Two readings, neither a rate:

1. The loop closes the failure that is a **missing slot** and does not close the failure that is
   a **wrong order** — the same distinction §7d and the ordering ablation draw, now seen from
   the repair side. An ordering requirement is not a page that can be inserted.
2. Three attempts produced three different decks and no convergence, so a repair budget cannot
   rest on "it will converge"; it has to be set by cost.

With two failures this is a mechanism, not an effect size. The main grid (DeepSeek) is
**unrepaired**: its key had no balance when the loop was ready, and 67% there remains a
first-pass figure.

## 9. Reproduction commands

```bash
export DEEPSEEK_API_KEY=sk-xxxx

# main table
python -m kgslide.bench --units U10,U11,U12 \
  --modes full,zero_shot,rag,cot --repeat 3 --out outputs/bench_main

# ablations
python -m kgslide.bench --units U10,U11,U12 \
  --modes full,no_order,no_misconception,no_forbidden \
  --repeat 2 --out outputs/bench_ablation

# re-score after a metric change, without calling the API
# (cheaper, and guaranteed to correspond exactly to the original outputs)
python -m kgslide.bench --units U10,U11,U12 \
  --modes full,zero_shot,rag,rag_mc,cot --repeat 3 \
  --out outputs/bench_main --reuse

# robustness check with thinking mode disabled
python -m kgslide.bench --units U10,U11,U12 \
  --modes full,zero_shot --repeat 2 --thinking disabled --out outputs/bench_nothink

# cross-model replication (second backbone; note temperature is pinned at 1.0 by the vendor)
python -m kgslide.bench --provider kimi --units U10,U11,U12 \
  --modes full,rag_mc,rag,placebo,cot,zero_shot --repeat 3 --out outputs/bench_kimi

# second course: build the graph, then run the 12 cells (needs AGNES_API_KEY)
python data/build_cpp_m4.py
PYTHONPATH=src python -m kgslide.bench --provider agnes \
  --kg data/kg_cpp_m4.json --units U41,U42 \
  --modes full,rag_mc,zero_shot --repeat 2 --out outputs/bench_cpp

# the second-course table (Table 6 in the paper)
python paper/tables.py --course-b outputs/bench_cpp

# backbone × course sweep (Table 7 in the paper)
python paper/tables.py --sweep "DeepSeek V4|Python|outputs/main_v1;Kimi K3|Python|outputs/bench_kimi;agnes-2.5-flash|Python|outputs/bench_py_agnes;agnes-2.5-flash|C++|outputs/bench_cpp"

# concept-level pairing (§5.4, supplementary S5; no API calls)
python paper/concept_pairs.py            # print the per-baseline pairing tables
python paper/concept_pairs.py --latex    # write paper/latex/concept_pairs.tex

# repair loop (§8): re-prompts the failing runs of one condition, then counts again
PYTHONPATH=src python paper/repair_loop.py --source outputs/bench_py_agnes \
  --modes full --provider agnes --out outputs/repair_agnes --rounds 3 --max-calls 6
```

Every cell leaves three files behind: `.pptx` (the artefact), `.json` (the raw model output)
and `.report.md` (item-by-item findings). Any number in the paper can be traced back through
these three files.
