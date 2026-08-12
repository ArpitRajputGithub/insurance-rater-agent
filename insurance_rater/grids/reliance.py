"""Reliance -- Comprehensive. RTO code -> region_city -> OD column, minus the
<1000cc footnote. TP payout is on OD premium only (STP column = 0).
"""
from __future__ import annotations

import re

from ..models import ComponentRate, Status, TraceStep
from .common import _unsupported, _wb, _xls_cite


def resolve(facts, raters_dir):
    key = "reliance"
    trace = []
    wb = _wb(key, raters_dir)

    rto = facts.get("rto_code")
    if not rto:
        r = _unsupported("od", "No RTO code extracted; cannot map to a Reliance region.")
        return r, _unsupported("tp", r.reason), trace

    # 1. RTO code -> Region_City (RTO List sheet, col A -> col C).
    rl = wb["RTO List"]
    city = crow = None
    for r in range(1, rl.max_row + 1):
        if str(rl.cell(r, 1).value).strip().upper() == rto.upper():
            city, crow = rl.cell(r, 3).value, r
            break
    if city is None:
        r = _unsupported("od", f"RTO code {rto} not found in the Reliance 'RTO List'.")
        return r, _unsupported("tp", r.reason), trace
    c1 = _xls_cite(key, "RTO List", crow, 3, f"{rto} -> Region_City '{city}'")
    trace.append(TraceStep(f"RTO {rto} maps to Reliance region '{city}'",
                           facts.facts.get("rto_code").citation, c1))

    # 2. region -> rate row (PRIVATE CAR COMP, SAOD & STP).
    rs = wb["PRIVATE CAR COMP, SAOD & STP"]
    rrow = None
    for r in range(3, rs.max_row + 1):
        if str(rs.cell(r, 2).value).strip().lower() == str(city).strip().lower():
            rrow = r
            break
    if rrow is None:
        r = _unsupported("od", f"Region '{city}' not found in the Reliance rate sheet.", [c1])
        return r, _unsupported("tp", r.reason, [c1]), trace

    petrol_od = rs.cell(rrow, 3).value       # 'Petrol/Bifuel/Comp'
    diesel_od = rs.cell(rrow, 4).value       # 'Diesel/EV/Comp'
    stp = rs.cell(rrow, 6).value             # 'STP'
    sheet = "PRIVATE CAR COMP, SAOD & STP"

    # Fuel is not printed on the Reliance schedule. If petrol and diesel columns
    # differ we cannot silently pick one -> only resolve on a documented rule:
    # no CNG/LPG kit fitted and <1000cc, for which no diesel passenger variant
    # exists, so the Petrol/Bifuel column is the supported reading (medium conf).
    cc = facts.get("cc")
    kit = facts.get("cng_lpg_kit")
    if _pct_or(petrol_od) == _pct_or(diesel_od):
        base, note = petrol_od, "petrol and diesel columns agree"
    elif kit is False and cc is not None and cc < 1000:
        base = petrol_od
        note = ("fuel not printed; no CNG/LPG kit and <1000cc (no diesel variant "
                "exists), so the Petrol/Bifuel column applies")
        facts.warnings.append("Reliance: fuel assumed Petrol/Bifuel (not on schedule; "
                              "no CNG kit, <1000cc).")
    else:
        r = ComponentRate("od", True, Status.AMBIGUOUS, None, citations=[c1],
                          reason=("Reliance OD differs by fuel (Petrol/Bifuel "
                                  f"{petrol_od} vs Diesel/EV {diesel_od}) and fuel is "
                                  "not printed on the schedule."))
        return r, _reliance_tp(key, sheet, rrow, stp), trace
    c2 = _xls_cite(key, sheet, rrow, 3, f"{city} Petrol/Bifuel/Comp = {base}%")
    trace.append(TraceStep(f"Region '{city}' OD (Petrol/Bifuel) = {base}% ({note})", None, c2))

    rate = float(base)
    cites = [c1, c2]
    # 3. Sub-cc OD footnote (cell H3). Both numbers -- the cc threshold and the %
    # cut -- live in the cell text, and the card is replaced monthly, so read
    # them from the cell instead of hard-coding. If H3 looks like a cc rule we
    # can't parse, flag it rather than apply a stale constant (fail loud, not
    # silently wrong).
    foot = str(rs.cell(3, 8).value or "")
    parsed = _cc_footnote(foot)
    applied = None  # (threshold, cut) actually applied
    if parsed and cc is not None and cc < parsed[0]:
        threshold, cut = parsed
        rate -= cut
        applied = parsed
        c3 = _xls_cite(key, sheet, 3, 8, f"footnote: <{threshold}cc -> {cut:g}% lesser ({foot})")
        cites.append(c3)
        trace.append(TraceStep(f"Footnote: {cc}cc < {threshold}cc -> -{cut:g}% -> OD {rate:g}%", None, c3))
    elif parsed is None and cc is not None and "cc" in foot.lower():
        facts.warnings.append("Reliance sub-cc OD footnote (H3) could not be parsed; no "
                              f"adjustment applied -- verify the rate card. Footnote: {foot!r}")

    od = ComponentRate("od", True, Status.RESOLVED, round(rate, 3), citations=cites,
                       reason=f"Reliance {city} OD ({note}) minus <{applied[0]}cc footnote."
                       if applied else f"Reliance {city} OD ({note}).")
    return od, _reliance_tp(key, sheet, rrow, stp), trace


def _pct_or(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_CC_FOOTNOTE = re.compile(r"<\s*(\d+)\s*CC.*?(\d+(?:\.\d+)?)\s*%\s*less", re.I)


def _cc_footnote(text: str):
    """Reliance sub-cc OD footnote -> (threshold_cc, deduction_pct), or None.

    Reads both numbers from the cell text (e.g. '< 1000 CC ... 5% lesser') so a
    new month's card -- a changed threshold or % -- is honoured with no code
    change, and returns None on any other text so the caller can flag it.
    """
    m = _CC_FOOTNOTE.search(text or "")
    return (int(m.group(1)), float(m.group(2))) if m else None


def _reliance_tp(key, sheet, rrow, stp):
    # Grid note H2: payout is on OD premium only. A blank STP cell is a missing
    # rule -> unsupported, never a fabricated zero.
    val = _pct_or(stp)
    if val is None:
        return _unsupported("tp", "Reliance STP column is blank for this region; the "
                            "Third Party payout cannot be confirmed from the grid.",
                            [_xls_cite(key, sheet, rrow, 6, "STP column is blank")])
    c = _xls_cite(key, sheet, rrow, 6, f"STP column = {stp}; payout is on OD premium only")
    return ComponentRate("tp", True, Status.RESOLVED, round(val, 3), citations=[c],
                         reason="Reliance pays commission on OD premium only (grid note); "
                                f"the Third Party (STP) column reads {val:g}%.")
