"""Tata AIG -- Private Car. One 'Pvtcar' grid publishes all three covers in a
'Section Text' column: Package (comprehensive), SATP, SAOD. We discover which
covers the card actually carries, dispatch on the policy's cover, and read the
rate from the RTO-cluster column for the matching fuel/business rows.

Commission basis is stated by the card itself (General Guidelines): 'SATP on
Net Premium; Package and SAOD on OD premium'. So Package/SAOD land on OD and
SATP on TP -- we re-read that note every call and refuse if it changed, rather
than bake the assumption in.
"""
from __future__ import annotations

import re
from datetime import date

from ..models import ComponentRate, Status, TraceStep
from .common import (_na, _norm, _struct_changed, _unsupported, _wb, _xls_cite,
                     find_row, header_map)

_INSURER = "Tata AIG"
_SHEET = "Pvtcar"
# Section-Text value <-> our policy_type, and which component the rate feeds.
_SECTION_BY_COVER = {"comprehensive": "Package", "satp": "SATP", "saod": "SAOD"}
_COVER_BY_SECTION = {v.lower(): k for k, v in _SECTION_BY_COVER.items()}
_COMPONENT_BY_COVER = {"comprehensive": "od", "saod": "od", "satp": "tp"}


def _basis_cite(wb):
    """Verify + cite the card's own commission-basis note; None if it changed.

    The note is what tells us Package/SAOD are OD-based and SATP is TP-based --
    i.e. which component each rate belongs to. If the card ever restates it, we
    must not keep assuming the old mapping.
    """
    if "General Guidelines" not in wb.sheetnames:
        return None
    gg = wb["General Guidelines"]
    for r in range(1, min(gg.max_row, 60) + 1):
        for c in range(1, min(gg.max_column, 12) + 1):
            t = _norm(gg.cell(r, c).value)
            if "satp on net premium" in t and "package and saod on od premium" in t:
                return _xls_cite("tata_aig", "General Guidelines", r, c,
                                 "commission basis: SATP on Net Premium; "
                                 "Package & SAOD on OD premium")
    return None


def _candidate_rows(ws, data0, cols, section, fuel_key, biz_ok, rate_cols, seg_ok):
    """(row, col, value) for rows matching cover/fuel/business (and segment when
    pinned) in every candidate rate column."""
    out = []
    for r in range(data0, ws.max_row + 1):
        if (_norm(ws.cell(r, cols["fuel type"]).value) == _norm(fuel_key)
                and _norm(ws.cell(r, cols["section text"]).value) == _norm(section)
                and str(ws.cell(r, cols["business type"]).value).strip() in biz_ok
                and (seg_ok is None
                     or str(ws.cell(r, cols["type"]).value).strip() in seg_ok)):
            for _, col in rate_cols:
                v = ws.cell(r, col).value
                if v is not None:
                    out.append((r, col, v))
    return out


def _rate_columns(cols, facts):
    """[(header, col)] the rate may sit in, plus a human 'how' string.

    Exact RTO-location column first (e.g. DELHI). Otherwise the state's own
    column (HARYANA), else the state's code-prefixed cluster columns (UP ->
    UP1/UP2/UP3). Which cluster an RTO belongs to is not published in the card,
    so cluster columns are only usable together: the caller converges across
    them and refuses if they disagree, which keeps the fallback honest.
    """
    rto = facts.get("rto_location")
    if rto and _norm(rto) in cols:
        return [(str(rto).upper(), cols[_norm(rto)])], f"RTO location '{rto}'"
    state = facts.get("rto_state")
    if state and _norm(state) in cols:
        return ([(str(state).upper(), cols[_norm(state)])],
                f"state '{state}' (RTO '{rto}' has no own column)")
    code = str(facts.get("rto_code") or "")[:2].lower()
    if code:
        hits = sorted((h.upper(), c) for h, c in cols.items()
                      if re.fullmatch(re.escape(code) + r"\d+", h))
        if hits:
            return hits, (f"'{code.upper()}' cluster columns for RTO '{rto}' "
                          "(cluster membership not published in the card)")
    return [], None


def resolve(facts, raters_dir):
    key = "tata_aig"
    trace = []
    cover = facts.policy_type
    component = _COMPONENT_BY_COVER.get(cover)  # 'od' | 'tp' | None
    other = "tp" if component == "od" else "od"

    wb = _wb(key, raters_dir)
    if _SHEET not in wb.sheetnames:
        return (_struct_changed("od", _INSURER, f"the '{_SHEET}' sheet"),
                _struct_changed("tp", _INSURER, f"the '{_SHEET}' sheet"), trace)
    ws = wb[_SHEET]

    # Anchor the header row + label columns instead of trusting fixed indices.
    hdr = find_row(ws, "Section Text", "Fuel Type", "Business Type")
    if hdr is None:
        what = "the Section Text / Fuel Type / Business Type header row"
        return _struct_changed("od", _INSURER, what), _struct_changed("tp", _INSURER, what), trace
    cols = header_map(ws, hdr)
    data0 = hdr + 1

    basis = _basis_cite(wb)
    if basis is None:
        what = "the commission-basis note (General Guidelines)"
        return _struct_changed("od", _INSURER, what), _struct_changed("tp", _INSURER, what), trace

    # Which covers does the card actually publish? (data-driven, not assumed.)
    present = {_COVER_BY_SECTION[s] for r in range(data0, ws.max_row + 1)
               if (s := _norm(ws.cell(r, cols["section text"]).value)) in _COVER_BY_SECTION}
    if cover not in present:
        msg = (f"Tata AIG '{_SHEET}' grid does not publish a '{cover}' table "
               f"(card publishes: {', '.join(sorted(present)) or 'none'}).")
        return _unsupported("od", msg), _unsupported("tp", msg), trace

    section = _SECTION_BY_COVER[cover]

    # RTO -> grid column(s): exact location, else state column / state clusters.
    if not (facts.get("rto_location") or facts.get("rto_state") or facts.get("rto_code")):
        r = _unsupported(component, "Missing RTO location; cannot select a Tata "
                         f"'{_SHEET}' column.")
        return _by_component(component, r, other, cover, basis) + (trace,)
    rcols, how = _rate_columns(cols, facts)
    if not rcols:
        r = _unsupported(component,
                         f"RTO '{facts.get('rto_location')}' is not a column in the "
                         f"Tata AIG '{_SHEET}' grid and no state column matched.")
        return _by_component(component, r, other, cover, basis) + (trace,)
    names = "/".join(h for h, _ in rcols)
    colcite = _xls_cite(key, _SHEET, hdr, rcols[0][1], f"rate column(s) {names}")
    src = (facts.facts.get("rto_location") or facts.facts.get("rto_state")
           or facts.facts.get("rto_code"))
    trace.append(TraceStep(f"{how} -> Tata grid column(s) {names}",
                           src.citation if src else None, colcite))

    fuel = facts.get("fuel")
    if not fuel:
        r = _unsupported(component, "Missing fuel type; cannot pick a Tata row.", [colcite])
        return _by_component(component, r, other, cover, basis) + (trace,)

    # Map the schedule's fuel onto the grid's own labels for this section. The
    # grid has no Petrol label: Diesel/CNG/Electric get their own rows and
    # petrol/LPG sit under 'Other Than Diesel'.
    section_rows = [r for r in range(data0, ws.max_row + 1)
                    if _norm(ws.cell(r, cols["section text"]).value) == _norm(section)]
    fuel_labels = {str(ws.cell(r, cols["fuel type"]).value).strip() for r in section_rows}
    fuel_key = next((l for l in fuel_labels if _norm(l) == _norm(fuel)), None)
    if fuel_key is None and fuel.lower() in ("petrol", "lpg"):
        fuel_key = next((l for l in fuel_labels if _norm(l) == "other than diesel"), None)
    if fuel_key is None:
        r = _unsupported(component, f"Fuel '{fuel}' has no {section} fuel row in the "
                         f"Tata grid (labels: {sorted(fuel_labels)}).", [colcite])
        return _by_component(component, r, other, cover, basis) + (trace,)

    # Business type: Brand New for a current-year car; otherwise the previous
    # insurer decides -- Tata again is a Renewal, anyone else a Rollover. With
    # no previous-insurer line we keep both and rely on convergence.
    year = facts.get("regn_year") or facts.get("mfg_year")
    is_used = isinstance(year, int) and year < date.today().year
    prev = facts.get("prev_insurer")
    if not is_used:
        biz_ok = {"Brand New"}
    elif prev:
        biz_ok = {"Renewal"} if "tata" in str(prev).lower() else {"Rollover"}
        trace.append(TraceStep(
            f"Previous insurer '{prev}' -> business type {next(iter(biz_ok))}",
            facts.facts.get("prev_insurer").citation, None))
    else:
        biz_ok = {"Renewal", "Rollover"}

    # Segment: pin it only when the schedule's body type matches a grid segment
    # label (SUV -> 'MPV SUV'); otherwise keep all segments and converge.
    seg_ok = None
    body = facts.get("body_type")
    if body and "type" in cols:
        segs = {str(ws.cell(r, cols["type"]).value).strip() for r in section_rows}
        hit = {s for s in segs if _norm(body) and _norm(body) in _norm(s)}
        if hit:
            seg_ok = hit
            trace.append(TraceStep(
                f"Body type '{body}' narrows segment to {sorted(hit)}",
                facts.facts.get("body_type").citation, None))

    matches = _candidate_rows(ws, data0, cols, section, fuel_key, biz_ok, rcols, seg_ok)
    if not matches:
        r = _unsupported(component, f"No Tata {section} rows for fuel '{fuel_key}', "
                         f"business {sorted(biz_ok)} in {names}.", [colcite])
        return _by_component(component, r, other, cover, basis) + (trace,)

    vals = {round(float(v) * 100, 3) for _, _, v in matches}
    rows = sorted({r for r, _, _ in matches})
    span = _xls_cite(key, _SHEET, rows[0], rcols[0][1],
                     f"{fuel_key} {section}, {'/'.join(sorted(biz_ok))} "
                     f"(rows {rows[0]}-{rows[-1]}) in {names}")
    if len(vals) == 1:
        rate = vals.pop()
        trace.append(TraceStep(
            f"{fuel_key} {section} {'/'.join(sorted(biz_ok))} in {names}: all "
            f"{len(matches)} candidate cells converge -> {component.upper()} {rate:g}%",
            None, span))
        rated = ComponentRate(component, True, Status.RESOLVED, rate,
                              citations=[colcite, span, basis],
                              reason=(f"Tata AIG {section} rate for {fuel_key} in {names}; "
                                      f"every candidate cell agrees at {rate:g}% "
                                      f"({basis.detail})."))
    else:
        trace.append(TraceStep(
            f"{fuel_key} {section} in {names}: candidate cells disagree {sorted(vals)}",
            None, span))
        rated = ComponentRate(component, True, Status.AMBIGUOUS, None,
                              citations=[colcite, span],
                              reason=(f"Tata AIG {section} rate for {fuel_key} in {names} "
                                      f"still depends on segment/business type, which the "
                                      f"schedule does not pin down ({sorted(vals)})."))
    return _by_component(component, rated, other, cover, basis) + (trace,)


def _by_component(component, rated, other, cover, basis):
    """Place `rated` in its OD/TP slot; the other slot is a documented n/a.

    A SAOD carries no third-party cover and a SATP no own-damage cover, so the
    unrated side is 'not applicable', never 0% -- with the card's basis note.
    """
    na_reason = {
        "tp": "Stand-alone Own Damage / Package: Tata pays commission on OD "
              f"premium only, so no separate TP commission applies ({basis.detail}).",
        "od": "Stand-alone Third Party policy carries no own-damage cover, so no "
              f"OD commission applies ({basis.detail}).",
    }[other]
    na = _na(other, na_reason)
    return (rated, na) if component == "od" else (na, rated)
