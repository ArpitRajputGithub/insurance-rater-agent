"""CLI:  python -m insurance_rater <policy.pdf | dir> [--raters DIR] [--out DIR]

Rates one policy PDF (or every *.pdf in a directory) and prints the structured
JSON result to stdout. With --out, also writes <name>.json per policy.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from .agent import rate_policy

_DEFAULT_RATERS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bundle", "raters")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="insurance_rater")
    ap.add_argument("path", help="policy PDF, or a directory of policy PDFs")
    ap.add_argument("--raters", default=_DEFAULT_RATERS, help="raters/ grid directory")
    ap.add_argument("--out", help="directory to also write <name>.json into")
    args = ap.parse_args(argv)

    if os.path.isdir(args.path):
        pdfs = sorted(glob.glob(os.path.join(args.path, "*.pdf")))
    else:
        pdfs = [args.path]
    if not pdfs:
        ap.error(f"no PDF found at {args.path}")
    if args.out:
        os.makedirs(args.out, exist_ok=True)

    results = []
    for pdf in pdfs:
        result = rate_policy(pdf, args.raters).to_dict()
        result["policyFile"] = os.path.basename(pdf)
        results.append(result)
        if args.out:
            name = os.path.splitext(os.path.basename(pdf))[0] + ".json"
            with open(os.path.join(args.out, name), "w") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

    json.dump(results if len(results) > 1 else results[0], sys.stdout,
              indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
