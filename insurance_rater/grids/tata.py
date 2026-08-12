"""Tata AIG -- Stand-alone TP. RTO location -> grid column, then fuel/business
type -> SATP rate, converging across the unmapped vehicle segments.
"""
from __future__ import annotations

from datetime import date

from ..models import ComponentRate, Status, TraceStep
from .common import _na, _unsupported, _wb, _xls_cite


def resolve(facts, raters_dir):
    key = "tata_aig"
    trace = []
    od = _na("od", "This rate card covers Stand-alone TP only; Own Damage is not "
                   "rated here, so no OD commission applies.")
    wb = _wb(key, raters_dir)
    ws = wb["Pvtcar"]

    rto = facts.get("rto_location")
    fuel = facts.get("fuel")
    if not rto or not fuel:
        return od, _unsupported("tp", "Missing RTO location or fuel; cannot select a "
                                      "Tata Pvtcar column/row."), trace

    # 1. RTO location -> grid column (header row 5).
    col = None
    for c in range(13, ws.max_column + 1):
        if str(ws.cell(5, c).value).strip().upper() == rto.strip().upper():
            col = c
            break
    if col is None:
        return od, _unsupported("tp", f"RTO location '{rto}' is not a column in the "
                                      "Tata AIG 'Pvtcar' grid."), trace
    colcite = _xls_cite(key, "Pvtcar", 5, col, f"RTO cluster column '{rto}'")
    trace.append(TraceStep(f"RTO '{rto}' maps to Tata grid column '{rto}'",
                           facts.facts.get("rto_location").citation, colcite))

    # 2. Business type: a used car (regn/mfg year in the past) is Renewal or
    #    Rollover, never Brand New. We cannot tell which, and the exact vehicle
    #    segment is not mapped -- so gather EVERY non-new CNG/SATP row and resolve
    #    only if they converge.
    year = facts.get("regn_year") or facts.get("mfg_year")
    is_used = isinstance(year, int) and year < date.today().year
    biz_ok = {"Renewal", "Rollover"} if is_used else {"Brand New"}
    fuel_key = "CNG" if fuel.upper() == "CNG" else fuel.title()

    matches = []  # (row, value)
    for r in range(6, ws.max_row + 1):
        if (str(ws.cell(r, 9).value).strip() == fuel_key
                and str(ws.cell(r, 10).value).strip() == "SATP"
                and str(ws.cell(r, 8).value).strip() in biz_ok):
            v = ws.cell(r, col).value
            if v is not None:
                matches.append((r, v))
    if not matches:
        return od, _unsupported("tp", f"No Tata SATP rows for fuel '{fuel_key}', "
                                      f"business {sorted(biz_ok)} in '{rto}'.",
                                [colcite]), trace

    vals = {round(float(v) * 100, 3) for _, v in matches}
    rows = [r for r, _ in matches]
    span = _xls_cite(key, "Pvtcar", rows[0], col,
                     f"{fuel_key} SATP, {'/'.join(sorted(biz_ok))}, all segments "
                     f"(rows {rows[0]}-{rows[-1]}) in '{rto}'")
    if len(vals) == 1:
        rate = vals.pop()
        trace.append(TraceStep(
            f"{fuel_key} SATP {'/'.join(sorted(biz_ok))} in '{rto}': all "
            f"{len(matches)} candidate rows converge -> TP {rate:g}%", None, span))
        tp = ComponentRate("tp", True, Status.RESOLVED, rate, citations=[colcite, span],
                           reason=(f"Tata AIG SATP rate for {fuel_key} in {rto}; every "
                                   f"non-new segment/business-type row agrees at {rate:g}%."))
    else:
        trace.append(TraceStep(
            f"{fuel_key} SATP in '{rto}': candidate rows disagree {sorted(vals)}", None, span))
        tp = ComponentRate("tp", True, Status.AMBIGUOUS, None, citations=[colcite, span],
                           reason=(f"Tata AIG SATP rate for {fuel_key} in {rto} depends on "
                                   f"segment/business type, which could not be pinned down "
                                   f"and do not agree ({sorted(vals)})."))
    return od, tp, trace
