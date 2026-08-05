# Insurance Rater Agent

Reads a scanned motor-policy PDF, finds the broker commission the insurer pays
on each coverage component — **Own Damage (OD)** and **Third Party (TP)** — by
looking it up in that insurer's rate card, and cites the exact cell behind every
number. When the evidence does not support a rate, it says so and shows why
instead of guessing.

## Results

| Policy | Insurer | Type | OD | TP | Overall | Confidence |
|---|---|---|---|---|---|---|
| `pvt-car-comprehensive-hdfc-ergo` | HDFC ERGO | Comprehensive | **17.5%** (Zone-2 · Package · >10-50k slab) | **unsupported** (grid has no TP table) | unsupported | medium |
| `pvt-car-satp-go-digit` | Go Digit | SATP | *n/a* | **29.5%** (UP_Bad cluster · Petrol>1000) | resolved | high |
| `pvt-car-comprehensive-reliance` | Reliance | Comprehensive | **17.5%** (Delhi 22.5% − 5% <1000cc footnote) | **0%** (payout on OD premium only) | resolved | medium |
| `pvt-car-satp-tata-aig` | Tata AIG | SATP | *n/a* | **38%** (Delhi CNG SATP) | resolved | high |

Full machine-readable traces (facts, citations, decision steps) are in
[`traces/`](traces/).

The HDFC row is the deliberate honest-refusal case: OD resolves to a cited
17.5%, but the grid publishes only Own-Damage-based rates and has **no** TP
table, so TP is returned `unsupported` with a reason — never a fabricated number.

## Setup

Requires Python 3.11+ and **Tesseract OCR** (the policies are scanned images).

```bash
brew install tesseract                 # macOS; apt-get install tesseract-ocr on Debian/Ubuntu
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
# one policy -> JSON on stdout
python -m insurance_rater bundle/sample-policies/pvt-car-comprehensive-hdfc-ergo.pdf

# a whole directory -> one <name>.json per policy into traces/
python -m insurance_rater bundle/sample-policies --out traces

# point at a different rate-card directory
python -m insurance_rater path/to/policy.pdf --raters path/to/raters
```

OCR output is cached under `insurance_rater/.ocr_cache/` (keyed by file hash), so
repeat runs and the test suite are fast.

## Tests

```bash
python -m pytest
```

`test_units.py` locks the deterministic logic (slab boundaries, segment banding,
status roll-up). `test_policies.py` runs all four policies end-to-end and asserts
both the rate **and** the exact grid cell cited.

## Architecture

```
PDF ─► ocr.py ─► extract.py ─────► grids.py ─────► agent.py ─► JSON
      (Tesseract) (fuzzy facts     (deterministic  (roll-up +
       + cache)    + citations)     lookup + cites)  confidence)
```

The design separates two concerns with a hard seam: **extraction may be fuzzy;
grid resolution must be reproducible.**

- **`ocr.py`** — renders each page at 400 dpi and runs Tesseract in three
  contrast/PSM passes, because the de-identified fixtures print fields at
  different grey levels and no single pass reads them all. Cached on disk.
- **`extract.py`** — the fuzzy half. Per-insurer regex parsers turn OCR text into
  a `PolicyFacts` bag; every fact carries a `Citation` and a `confident` flag, so
  genuine uncertainty survives instead of being silently filled in. Isolated
  behind `extract_policy()` so it could be swapped for a vision-LLM extractor.
- **`grids.py`** — the deterministic half. Opens the real `raters/` files
  (openpyxl for XLSX, pdfplumber for the HDFC PDF) and returns the exact
  `Sheet!Cell` or `page` behind each number. Nothing is hard-coded to the four
  answers — edit a grid cell and the output changes. A missing mapping yields
  `unsupported`, never an inferred rate.
- **`models.py` / `agent.py`** — stable dataclasses for the JSON, plus
  orchestration, status roll-up and confidence.

**Result states.** OD and TP are each independently `resolved` / `unsupported` /
`ambiguous`, with an `applicable` flag (`applicable=false` means *not
applicable*, e.g. OD on a TP-only policy — distinct from a rate of 0%). The
top-level status is the strongest component problem: ambiguous > unsupported >
resolved. Where a fact we could not extract does not change the answer because
every candidate cell holds the same rate, the component resolves by
**convergence** and the reason says so; where candidates disagree it returns
`ambiguous`.

## Assumptions

- **HDFC premium slab** reads on the *comprehensive* premium (Total Package
  Premium a+b = 11,869 → `>10-50k`), per the grid footnote — not the OD-only line
  (8,053, which would wrongly land in `<10k`).
- **Reliance fuel** is not printed, and OD differs by fuel. We resolve to the
  Petrol/Bifuel column only under a documented rule (no CNG/LPG kit fitted and
  <1000 cc, a band with no diesel variant), surfaced as a warning that caps
  confidence at medium.
- **Reliance TP = 0%** because the grid note pays commission on OD premium only
  and the stand-alone-TP column is 0 — a cited zero, not a missing rule.
- **RTO mapping is authoritative**: where a grid maps a code to a region (e.g.
  Reliance `UP-16` → Delhi), we follow the grid, not the code's nominal state.

## Trade-offs

- **Regex extraction over an LLM** — deterministic, offline, zero-cost and easy
  to test on four known fixtures. The seam lets a vision-LLM extractor replace it
  later without touching grid resolution.
- **Per-insurer resolvers over a generic engine** — the four rate cards share
  almost no structure (a 2-page PDF, a 14-sheet workbook, a 70-column matrix), so
  bespoke resolvers are smaller and more auditable than a configurable one.
- **Citations as first-class output** — every rate ships with the `Sheet!Cell` or
  `page` behind it, because "found in the grid" is not auditable.

Resilience: unread OCR fields surface as low-confidence or `unsupported`, never
wrong numbers; an unrecognised insurer returns a clean `unsupported`; the golden
tests catch grid-layout regressions.
