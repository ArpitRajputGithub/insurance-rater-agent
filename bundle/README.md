# Insurance Rater Agent Challenge

This starter bundle contains everything needed to complete the challenge offline.

## Contents

- `challenge.md` - domain primer, complete task, output contract, evaluation criteria and submission instructions.
- `sample-policies/` - four de-identified motor-policy PDFs, including an HDFC ERGO comprehensive policy and a Go Digit stand-alone TP policy.
- `raters/` - the four matching original-format brokerage grids: three XLSX workbooks and one PDF.
- `MANIFEST.json` - SHA-256 checksum and byte size for every bundled file.

Start with the OD/TP and commission-grid primer in `challenge.md`, then point your implementation at a file under `sample-policies/` and the local `raters/` directory. Treat the commission grids as authoritative and do not hard-code answers for the supplied policies.

The workbook and PDF metadata in this bundle has been sanitized. The original grid layouts, formulas, cached values, sheets and lookup content are retained.
