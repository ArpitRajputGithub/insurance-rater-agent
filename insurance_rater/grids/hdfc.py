"""HDFC ERGO -- Comprehensive. PDF grid: state->zone, then zone/slab/fuel/NCB.

The grid only publishes Package/SAOD (OD-based) rates; it has no TP table, so
TP is an honest UNSUPPORTED.
"""
from __future__ import annotations

import pdfplumber

from ..models import Citation, ComponentRate, Status, TraceStep
from .common import _source, _unsupported, grid_path

_HDFC_SLABS = [  # (label, upper-exclusive bound on comprehensive premium in rupees)
    ("<10k", 10_000), (">10-50k", 50_000), (">50k-1L", 100_000),
    (">1L-2L", 200_000), (">2L", float("inf")),
]


def _hdfc_slab(premium):
    for label, hi in _HDFC_SLABS:
        if premium < hi:
            return label
    return _HDFC_SLABS[-1][0]


def _pct(s):
    return float(str(s).replace("%", "").strip())


def _hdfc_read(path):
    """Parse the HDFC PDF into (zone_map, rate_tables, zone_page).

    zone_map: state(lower) -> 'Zone-1'|'Zone-2'
    rate_tables: {'Zone 1': {slab: {...}}, 'Zone 2': {...}}  (Package cols only)
    """
    zone_map, rates, zone_page = {}, {}, {}
    with pdfplumber.open(path) as pdf:
        for pidx, pg in enumerate(pdf.pages):
            for tbl in pg.extract_tables():
                head = (tbl[0][1] or "") if tbl and len(tbl[0]) > 1 else ""
                # Locate the 'Zone | State Name | ... | Zone-1 | Zone-2' header row,
                # which may sit under a leading blank row.
                hrow = next((i for i, r in enumerate(tbl)
                             if r and r[0] == "Zone" and (r[1] or "").startswith("State")), None)
                if head in ("Zone 1", "Zone 2"):
                    slabs = {}
                    for row in tbl[4:]:
                        if row and row[0]:
                            slabs[row[0].strip()] = {
                                "petrol": row[1], "nonpetrol_ncb": row[2],
                                "nonpetrol_nncb": row[3],
                            }
                    rates[head] = slabs
                elif hrow is not None:
                    for row in tbl[hrow + 1:]:
                        name = (row[1] or "").strip()
                        if not name:
                            continue
                        z1 = (row[3] or "").strip()
                        z2 = (row[6] or "").strip() if len(row) > 6 else ""
                        zone = "Zone-2" if z2 else ("Zone-1" if z1 else None)
                        if zone:
                            zone_map[name.lower()] = zone
                            zone_page[name.lower()] = pidx + 1
    return zone_map, rates, zone_page


def resolve(facts, raters_dir):
    key = "hdfc_ergo"
    src = _source(key)
    trace = []
    tp = _unsupported("tp", "The HDFC ERGO grid publishes only Package/SAOD "
                            "(Own-Damage-based) commission; it contains no Third "
                            "Party rate table, so the TP rate cannot be determined "
                            "from the supplied evidence.")

    state = facts.get("rto_state")
    slab_prem = facts.get("package_premium")
    if not state or slab_prem is None:
        return _unsupported("od", "Missing state or comprehensive premium; cannot "
                                  "look up the HDFC zone/slab."), tp, trace

    zone_map, rates, zone_page = _hdfc_read(grid_path(key, raters_dir))
    zone = zone_map.get(state.lower())
    if zone is None:
        return _unsupported("od", f"State '{state}' not found in the HDFC zone map."), tp, trace
    zc = Citation(src, f"page {zone_page.get(state.lower())}",
                  f"{state} -> {zone}")
    trace.append(TraceStep(f"{state} maps to HDFC {zone}",
                           facts.facts.get("rto_state").citation, zc))

    zkey = zone.replace("-", " ")  # 'Zone-2' -> 'Zone 2'
    slab = _hdfc_slab(slab_prem)
    trace.append(TraceStep(f"Comprehensive premium {slab_prem} -> slab {slab}",
                           facts.facts.get("package_premium").citation, None))
    cell = rates.get(zkey, {}).get(slab)
    if cell is None:
        return _unsupported("od", f"No HDFC {zkey} rate row for slab '{slab}'.", [zc]), tp, trace

    # Fuel is not printed on HDFC schedules. Candidate columns depend on NCB:
    #   petrol             -> 'petrol' column (same for NCB and N-NCB)
    #   non-petrol + NCB   -> 'nonpetrol_ncb'
    #   non-petrol + N-NCB -> 'nonpetrol_nncb'
    # We take every column consistent with what we do know and resolve only if
    # they converge; otherwise AMBIGUOUS.
    ncb = facts.get("ncb_applies")
    fuel = facts.get("fuel")
    cands = {}
    if fuel and fuel.lower() != "petrol":  # known non-petrol
        cands["nonpetrol"] = cell["nonpetrol_ncb"] if ncb else cell["nonpetrol_nncb"]
    elif fuel and fuel.lower() == "petrol":
        cands["petrol"] = cell["petrol"]
    else:  # fuel unknown -> both fuel families are candidates
        cands["petrol"] = cell["petrol"]
        cands["nonpetrol"] = cell["nonpetrol_ncb"] if ncb else cell["nonpetrol_nncb"]
    vals = {_pct(v) for v in cands.values()}
    # Rate tables live on page 1 of this grid.
    rc = Citation(src, "page 1", f"{zkey} · Package · slab {slab}: " +
                  ", ".join(f"{k}={cands[k]}" for k in cands))

    if len(vals) == 1:
        rate = vals.pop()
        cov = ("petrol and non-petrol columns agree" if len(cands) > 1
               else f"{next(iter(cands))} column")
        reason = (f"HDFC {zkey} Package, slab {slab} ({cov}"
                  + (", NCB applies" if ncb else "") + f") -> {rate:g}%.")
        trace.append(TraceStep(f"{zkey} · Package · {slab} -> OD {rate:g}% ({cov})", None, rc))
        od = ComponentRate("od", True, Status.RESOLVED, rate, citations=[zc, rc], reason=reason)
    else:
        reason = (f"HDFC {zkey} Package slab {slab} gives different rates by fuel "
                  f"({cands}); fuel is not printed on the schedule, so OD is ambiguous.")
        trace.append(TraceStep(f"{zkey} · Package · {slab} -> ambiguous by fuel {cands}", None, rc))
        od = ComponentRate("od", True, Status.AMBIGUOUS, None, citations=[zc, rc], reason=reason)
    return od, tp, trace
