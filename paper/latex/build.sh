#!/usr/bin/env bash
# Build the KBS manuscript.  Requires: pdflatex, bibtex (TeX Live / TinyTeX).
#
# Produces three PDFs from one source:
#   manuscript.pdf           review version: 12pt, double spaced, line numbers
#   manuscript-preprint.pdf  compact preprint: 12pt, single spaced, no line numbers
#   highlights.pdf           standalone Highlights page (5 bullets, <=85 chars each)
set -euo pipefail
cd "$(dirname "$0")"

pass() {  # pass <jobname>
  local job="$1"
  pdflatex -interaction=nonstopmode -halt-on-error "$job.tex" > "$job.log" 2>&1 || {
    echo "!! $job: compile failed"; grep -n -A4 '^!' "$job.log" | head -40; exit 1; }
  bibtex "$job" > "$job.bib.log" 2>&1 || true
  pdflatex -interaction=nonstopmode -halt-on-error "$job.tex" >> "$job.log" 2>&1
  pdflatex -interaction=nonstopmode -halt-on-error "$job.tex" >> "$job.log" 2>&1
}

report() {  # report <jobname> <label>
  local job="$1" label="$2"
  local over total
  # ``|| true`` matters: with ``pipefail`` a log with zero overfull boxes makes
  # ``grep`` return 1, which would abort the whole build on the cleanest input.
  over=$( (grep -o 'Overfull \\hbox ([0-9.]*pt too wide)' "$job.log" || true) \
         | sed 's/[^0-9.]//g' | awk '$1>4' | wc -l | tr -d ' ')
  total=$( (grep -c 'Overfull \\hbox' "$job.log" || true) | head -1)
  printf '%-10s overfull >4pt: %s   total overfull: %s   ' "$label" "$over" "$total"
  (grep -o 'Output written on .*pdf ([0-9]* pages' "$job.log" || true) | sed 's/.*(//' | tail -1
  echo
}

# ---- 1. review version -------------------------------------------------
pass manuscript
report manuscript review

# ---- 2. preprint version, generated from the same source ----------------
sed -e 's/\[review,12pt\]/[preprint,12pt]/' \
    -e 's/^\\linenumbers/%\\linenumbers/' \
    manuscript.tex > _preprint.tex
pass _preprint
mv _preprint.pdf manuscript-preprint.pdf
report _preprint preprint
rm -f _preprint.tex _preprint.aux _preprint.bbl _preprint.blg _preprint.log _preprint.out

# ---- 3. highlights (Elsevier requires this as a separate file) ----------
pdflatex -interaction=nonstopmode -halt-on-error highlights.tex > highlights.log 2>&1 || {
  echo "!! highlights: compile failed"; grep -n -A4 '^!' highlights.log | head -40; exit 1; }
printf '%-10s ' highlights
( grep -o 'Output written on .*pdf ([0-9]* page' highlights.log || true ) \
  | sed 's/.*(//' | tail -1 | sed 's/$/s/'; echo
rm -f highlights.aux highlights.log

# ---- 4. supplementary (S1 ablations, S2 graph-check mutations, S3 probe, S4 cross-model, S5 concept pairs) --
pass supplementary
report supplementary supplementary

# ---- 5. cover letter (separate upload item in EES) -----------------------
pass cover-letter
printf '%-10s ' cover-letter
( grep -o 'Output written on .*pdf ([0-9]* page' cover-letter.log || true ) \
  | sed 's/.*(//' | tail -1 | sed 's/$/s/'; echo
rm -f cover-letter.log

echo
ls -lh manuscript.pdf manuscript-preprint.pdf supplementary.pdf highlights.pdf cover-letter.pdf
