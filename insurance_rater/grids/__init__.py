"""Deterministic grid resolution: the reproducible half of the pipeline.

Extraction may be fuzzy or model-driven, but turning policy facts into a
commission rate must be reproducible and testable, and must never invent a
rate through a missing, declined or out-of-scope rule.

Each insurer's card lives in its own module (go_digit, hdfc, reliance, tata);
shared plumbing -- file locations, workbook loading, citation builders, and the
`_na` / `_unsupported` constructors -- lives in `common`. Every resolver reads
the actual rate-card files shipped in `raters/` and returns the exact sheet/cell
(or PDF page/table) that produced each number. Nothing is hard-coded to the four
sample answers: change a cell in a grid and the output changes with it. Where a
required mapping is absent we return UNSUPPORTED rather than guess.

Each resolver returns (od, tp, trace):
  * od / tp : ComponentRate   -- applicability + status + rate + citations
  * trace   : list[TraceStep] -- one auditable line per lookup

Convergence: sometimes a fact we could not extract (fuel, exact segment,
renewal-vs-rollover) does not change the answer because every candidate cell
holds the same rate. That is a resolution, not a guess, and the reason says so.
Where candidates disagree we return AMBIGUOUS instead.
"""
from __future__ import annotations

from ..models import PolicyFacts
from . import go_digit, hdfc, reliance, tata
from .common import _unsupported
from .go_digit import _godigit_segment
from .hdfc import _hdfc_slab
from .reliance import _cc_footnote

_RESOLVERS = {
    "go_digit": go_digit.resolve,
    "hdfc_ergo": hdfc.resolve,
    "reliance": reliance.resolve,
    "tata_aig": tata.resolve,
}


def resolve(facts: PolicyFacts, insurer_key: str, raters_dir: str):
    fn = _RESOLVERS.get(insurer_key)
    if fn is None:
        r = _unsupported("od", f"No grid resolver for insurer '{insurer_key}'.")
        return r, _unsupported("tp", r.reason), []
    if facts.policy_type not in ("saod", "comprehensive", "satp"):
        r = _unsupported("od", "Policy type could not be determined from the schedule; "
                               "refusing to assume one to select a grid.")
        return r, _unsupported("tp", r.reason), []
    return fn(facts, raters_dir)
