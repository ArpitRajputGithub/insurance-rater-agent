"""Reliance -- cover-aware. RTO code -> region (RTO List) -> the column that the
policy's cover reads from in the 'PRIVATE CAR COMP, SAOD & STP' sheet:

  * comprehensive : OD from Petrol/Bifuel/Comp or Diesel/EV/Comp (fuel rule),
                    TP from STP (grid note: payout on OD premium only).
  * saod          : OD from the 'SA OD' column; a stand-alone OD carries no
                    third-party cover, so TP is n/a (never 0%).
  * satp          : TP from the 'STP' column; no own-damage cover, so OD is n/a.

Columns are anchored on their header text and the <1000cc footnote is read from
the card, so a monthly reshuffle is survived (or refused) instead of mis-read.
"""
from __future__ import annotations

import re

from ..models import ComponentRate, Status, TraceStep
from .common import (_na, _norm, _struct_changed, _unsupported, _wb, _xls_cite,
                     find_row, header_map)

_INSURER = "Reliance"
_SHEET = "PRIVATE CAR COMP, SAOD & STP"
_COL_BY_COVER = {"saod": "sa od", "satp": "stp"}  # comprehensive is the fuel-rule path


def resolve(facts, raters_dir):
    key = "reliance"
    trace = []
    cover = facts.policy_type
    wb = _wb(key, raters_dir)

    rto = facts.get("rto_code")
    if not rto:
        r = _unsupported("od", "No RTO code extracted; cannot map to a Reliance region.")
        return r, _unsupported("tp", r.reason), trace

    # 1. RTO code -> Region_City (RTO List sheet, col A -> col C).
    if "RTO List" not in wb.sheetnames:
        return (_struct_changed("od", _INSURER, "the 'RTO List' sheet"),
                _struct_changed("tp", _INSURER, "the 'RTO List' sheet"), trace)
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

    # 2. Anchor the header row + columns, then the region's rate row.
    if _SHEET not in wb.sheetnames:
        return (_struct_changed("od", _INSURER, f"the '{_SHEET}' sheet"),
                _struct_changed("tp", _INSURER, f"the '{_SHEET}' sheet"), trace)
    rs = wb[_SHEET]
    hdr = find_row(rs, "RTO region", "SA OD", "STP")
    if hdr is None:
        what = "the RTO region / SA OD / STP header row"
        return _struct_changed("od", _INSURER, what), _struct_changed("tp", _INSURER, what), trace
    cols = header_map(rs, hdr)
    for need in ("rto region", "petrol/bifuel/comp", "diesel/ev/comp", "sa od", "stp"):
        if need not in cols:
            what = f"the '{need}' column"
            return _struct_changed("od", _INSURER, what), _struct_changed("tp", _INSURER, what), trace

    # Region rows can group cities ("Mumbai, Pune, Goa"), so match the city
    # against the cell's comma-separated tokens, not the whole cell.
    rrow = None
    for r in range(hdr + 1, rs.max_row + 1):
        tokens = [_norm(t) for t in str(rs.cell(r, cols["rto region"]).value or "").split(",")]
        if _norm(city) in tokens:
            rrow = r
            break
    if rrow is None:
        r = _unsupported("od", f"Region '{city}' not found in the Reliance rate sheet.", [c1])
        return r, _unsupported("tp", r.reason, [c1]), trace

    basis = _basis_cite(rs, hdr)

    # 3. Dispatch on the policy's cover.
    if cover == "satp":
        tp = _reliance_tp(key, rrow, cols["stp"], rs.cell(rrow, cols["stp"]).value)
        na = _na("od", "Stand-alone Third Party policy carries no own-damage cover, so "
                       "no OD commission applies.")
        return na, tp, trace

    if cover == "saod":
        col = cols["sa od"]
        base = rs.cell(rrow, col).value
        if _pct_or(base) is None:
            r = _unsupported("od", f"Reliance 'SA OD' column is blank for region '{city}'.",
                             [c1])
            return r, _na("tp", "Stand-alone Own Damage policy has no third-party cover."), trace
        c2 = _xls_cite(key, _SHEET, rrow, col, f"{city} SA OD = {base}%")
        trace.append(TraceStep(f"Region '{city}' SA OD = {base}%", None, c2))
        rate, cites = float(base), [c1, c2]
        rate = _apply_footnote(rs, key, facts, rate, cites, trace)
        od = ComponentRate("od", True, Status.RESOLVED, round(rate, 3), citations=cites,
                           reason=f"Reliance {city} stand-alone Own Damage rate.")
        return od, _na("tp", "Stand-alone Own Damage policy carries no third-party cover, "
                             "so no TP commission applies."), trace

    # comprehensive: OD from the fuel columns, TP from STP.
    petrol_od = rs.cell(rrow, cols["petrol/bifuel/comp"]).value
    diesel_od = rs.cell(rrow, cols["diesel/ev/comp"]).value
    stp = rs.cell(rrow, cols["stp"]).value

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
        return r, _reliance_tp(key, rrow, cols["stp"], stp), trace
    c2 = _xls_cite(key, _SHEET, rrow, cols["petrol/bifuel/comp"],
                   f"{city} Petrol/Bifuel/Comp = {base}%")
    trace.append(TraceStep(f"Region '{city}' OD (Petrol/Bifuel) = {base}% ({note})", None, c2))

    rate, cites = float(base), [c1, c2]
    rate = _apply_footnote(rs, key, facts, rate, cites, trace)
    od = ComponentRate("od", True, Status.RESOLVED, round(rate, 3), citations=cites,
                       reason=f"Reliance {city} OD ({note}).")
    return od, _reliance_tp(key, rrow, cols["stp"], stp), trace


def _basis_cite(rs, hdr):
    """Find + cite the grid's 'payout on OD premium' note; None if absent."""
    for r in range(1, min(rs.max_row, hdr + 2) + 1):
        for c in range(1, rs.max_column + 1):
            if "payout" in _norm(rs.cell(r, c).value) and "od premium" in _norm(rs.cell(r, c).value):
                return _xls_cite("reliance", _SHEET, r, c, "payout is on OD premium")
    return None


def _apply_footnote(rs, key, facts, rate, cites, trace):
    """Apply the sub-cc OD footnote if the card carries one and cc is under it.

    Both numbers -- the cc threshold and the % cut -- live in the note text, and
    the card is replaced monthly, so we read them from the anchored cell rather
    than hard-code. If a cc-looking note can't be parsed we flag it (fail loud)
    instead of applying a stale constant.
    """
    cc = facts.get("cc")
    cell = _find_footnote(rs)
    if cell is None:
        return rate
    frow, fcol, foot = cell
    parsed = _cc_footnote(foot)
    if parsed and cc is not None and cc < parsed[0]:
        threshold, cut = parsed
        rate -= cut
        c3 = _xls_cite(key, _SHEET, frow, fcol,
                       f"footnote: <{threshold}cc -> {cut:g}% lesser ({foot})")
        cites.append(c3)
        trace.append(TraceStep(f"Footnote: {cc}cc < {threshold}cc -> -{cut:g}% -> OD {rate:g}%",
                               None, c3))
    elif parsed is None and cc is not None and "cc" in foot.lower():
        facts.warnings.append("Reliance sub-cc OD footnote could not be parsed; no "
                              f"adjustment applied -- verify the rate card. Footnote: {foot!r}")
    return rate


def _find_footnote(rs):
    """(row, col, text) of the first cell holding a sub-cc payout note, or None."""
    for r in range(1, rs.max_row + 1):
        for c in range(1, rs.max_column + 1):
            t = str(rs.cell(r, c).value or "")
            if "cc" in t.lower() and "payout" in t.lower():
                return r, c, t
    return None


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


def _reliance_tp(key, rrow, stp_col, stp):
    # Grid note: payout is on OD premium only. A blank STP cell is a missing
    # rule -> unsupported, never a fabricated zero.
    val = _pct_or(stp)
    if val is None:
        return _unsupported("tp", "Reliance STP column is blank for this region; the "
                            "Third Party payout cannot be confirmed from the grid.",
                            [_xls_cite(key, _SHEET, rrow, stp_col, "STP column is blank")])
    c = _xls_cite(key, _SHEET, rrow, stp_col, f"STP column = {stp}; payout is on OD premium only")
    return ComponentRate("tp", True, Status.RESOLVED, round(val, 3), citations=[c],
                         reason="Reliance pays commission on OD premium only (grid note); "
                                f"the Third Party (STP) column reads {val:g}%.")
