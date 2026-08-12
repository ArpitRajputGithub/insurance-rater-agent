"""Go Digit -- Stand-alone TP. RTO code -> 4WTP cluster -> fuel/cc segment rate."""
from __future__ import annotations

from ..models import ComponentRate, Status, TraceStep
from .common import _na, _unsupported, _wb, _xls_cite


def _godigit_segment(fuel, cc):
    if fuel is None or cc is None:
        return None
    f = fuel.lower()
    if f == "cng":
        return "CNG"
    if f == "petrol":
        return "Petrol<1000" if cc < 1000 else "Petrol>1000"
    if f == "diesel":
        return "Diesel<1500" if cc < 1500 else "Diesel>1500"
    return None


_GODIGIT_NO_OD = ("The Go Digit 4W rate card only publishes a Stand-alone TP grid; "
                  "it has no Own Damage table, so OD cannot be rated here.")


def resolve(facts, raters_dir):
    key = "go_digit"
    trace = []
    # The card only carries a Stand-alone TP grid. What applies depends on the
    # product: SAOD is OD-only (TP n/a, OD unratable here); a package is both
    # (neither ratable from a TP-only grid); SATP is the one we can resolve.
    if facts.policy_type == "saod":
        return (_unsupported("od", _GODIGIT_NO_OD),
                _na("tp", "Stand-alone Own Damage policy carries no third-party "
                          "cover, so no TP commission applies."),
                trace)
    if facts.policy_type == "comprehensive":
        return (_unsupported("od", _GODIGIT_NO_OD),
                _unsupported("tp", "This card only publishes a Stand-alone TP grid; "
                                   "a package (OD+TP) TP rate is not available here."),
                trace)
    od = _na("od", "This rate card covers Stand-alone TP only; Own Damage is not "
                   "rated here, so no OD commission applies.")
    wb = _wb(key, raters_dir)

    rto = facts.get("rto_code")
    if not rto:
        return od, _unsupported("tp", "No RTO code extracted; cannot map to a "
                                      "Go Digit 4W TP cluster."), trace

    # 1. RTO code -> 4WTP cluster (column C of the '4W  RTO' sheet).
    rmap = wb["4W  RTO"]
    cluster = crow = None
    for r in range(1, rmap.max_row + 1):
        if str(rmap.cell(r, 2).value).strip().upper() == rto.upper():
            cluster, crow = rmap.cell(r, 3).value, r
            break
    if cluster is None:
        return od, _unsupported("tp", f"RTO code {rto} is not listed in the Go Digit "
                                      "'4W  RTO' mapping sheet."), trace
    c1 = _xls_cite(key, "4W  RTO", crow, 3, f"{rto} maps to 4WTP cluster '{cluster}'")
    trace.append(TraceStep(f"RTO {rto} maps to Go Digit TP cluster '{cluster}'",
                           facts.facts.get("rto_code").citation, c1))

    # 2. cluster + fuel/cc segment -> rate (column E 'Max CD2' of '4W SATP').
    seg = _godigit_segment(facts.get("fuel"), facts.get("cc"))
    if seg is None:
        return od, _unsupported("tp", "Could not form a Go Digit segment (need fuel "
                                      "and cc).", [c1]), trace
    rate_ws = wb["4W SATP"]
    rate = rrow = None
    for r in range(1, rate_ws.max_row + 1):
        if (str(rate_ws.cell(r, 2).value).strip() == str(cluster).strip()
                and str(rate_ws.cell(r, 3).value).strip() == seg):
            rate, rrow = rate_ws.cell(r, 5).value, r
            break
    if rate is None:
        return od, _unsupported("tp", f"No '4W SATP' row for cluster '{cluster}', "
                                      f"segment '{seg}'.", [c1]), trace
    c2 = _xls_cite(key, "4W SATP", rrow, 5, f"cluster '{cluster}', segment '{seg}' "
                                            f"-> {rate*100:g}%")
    trace.append(TraceStep(f"Segment '{seg}' in cluster '{cluster}' -> TP {rate*100:g}%",
                           None, c2))
    tp = ComponentRate("tp", True, Status.RESOLVED, round(rate * 100, 3),
                       citations=[c1, c2],
                       reason=f"Go Digit 4W SATP rate for {rto} ({cluster}) / {seg}.")
    return od, tp, trace
