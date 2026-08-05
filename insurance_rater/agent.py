"""Agent orchestration: policy PDF -> extract -> resolve -> AgentResult.

This is the thin seam that joins the fuzzy extractor to the deterministic grid
resolver and rolls their per-component outcomes up into one auditable result:
top-level status, per-component OD/TP rates + citations, a full decision trace,
and a confidence the caller can trust.
"""
from __future__ import annotations

from . import grids, ocr
from .extract import detect_insurer, extract_policy
from .models import AgentResult, Confidence, Status


def _facts_json(pf):
    out = {}
    for k, f in pf.facts.items():
        out[k] = {
            "value": f.value,
            "confident": f.confident,
            "citation": str(f.citation) if f.citation else None,
            "note": f.note or None,
        }
    return out


def _rollup(od, tp):
    """Top-level status from the applicable components.

    Ambiguous (conflicting evidence) takes precedence, then Unsupported
    (evidence missing), else Resolved. A not-applicable component (OD on a TP
    policy) is excluded -- its absence is by design, not a failure.
    """
    applicable = [c for c in (od, tp) if c.applicable]
    statuses = {c.status for c in applicable}
    if Status.AMBIGUOUS in statuses:
        return Status.AMBIGUOUS
    if Status.UNSUPPORTED in statuses:
        return Status.UNSUPPORTED
    return Status.RESOLVED


def _confidence(top, od, tp, warnings):
    applicable = [c for c in (od, tp) if c.applicable]
    resolved = [c for c in applicable if c.status is Status.RESOLVED]
    if top is Status.RESOLVED and not warnings:
        return Confidence("high", "Every applicable component resolved to a cited "
                                  "grid rate with no assumptions.")
    if resolved:
        # Name what did resolve (with its rate) so the medium level cannot be
        # misread as a total failure, then name each gap and why.
        got = ", ".join(f"{c.component.upper()} resolved ({c.rate_percent:g}%)"
                        for c in resolved)
        gaps = [f"{c.component.upper()} {c.status.value} — {c.reason}"
                for c in applicable if c.status is not Status.RESOLVED]
        bits = [got] + gaps
        if warnings:
            bits.append("a documented assumption was needed")
        return Confidence("medium", "; ".join(bits))
    return Confidence("low", "No applicable component could be resolved from the "
                             "supplied grid evidence.")


def rate_policy(pdf_path: str, raters_dir: str) -> AgentResult:
    pf = extract_policy(pdf_path)
    insurer_key = detect_insurer(ocr.page_texts(pdf_path))

    if insurer_key is None:
        od = grids._unsupported("od", "Insurer not recognised; no grid to resolve against.")
        tp = grids._unsupported("tp", od.reason)
        trace = []
    else:
        od, tp, trace = grids.resolve(pf, insurer_key, raters_dir)

    top = _rollup(od, tp)
    conf = _confidence(top, od, tp, pf.warnings)
    return AgentResult(
        status=top,
        insurer=pf.insurer,
        policy_type=pf.policy_type,
        facts=_facts_json(pf),
        od=od,
        tp=tp,
        trace=trace,
        confidence=conf,
        warnings=pf.warnings,
    )
