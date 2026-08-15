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
_GODIGIT_POINTER = (" The '4W  RTO' sheet maps this RTO to '4W Package' and '4WSAOD' "
                    "clusters, but the rate tables those clusters point to are not in "
                    "the shared workbook -- request them from Go Digit to rate this "
                    "policy.")


def _mapping_cites(key, raters_dir, rto):
    """Cite the '4W  RTO' Package/SAOD mapping cells for this RTO: proof the
    card points at OD/SAOD cluster tables it does not itself contain."""
    if not rto:
        return []
    try:
        rmap = _wb(key, raters_dir)["4W  RTO"]
    except Exception:
        return []
    for r in range(1, rmap.max_row + 1):
        if str(rmap.cell(r, 2).value).strip().upper() == str(rto).upper():
            pkg, saod = rmap.cell(r, 4).value, rmap.cell(r, 5).value
            return [_xls_cite(key, "4W  RTO", r, 4, f"{rto} -> 4W Package cluster "
                              f"'{pkg}' (its rate table is not in this workbook)"),
                    _xls_cite(key, "4W  RTO", r, 5, f"{rto} -> 4WSAOD cluster "
                              f"'{saod}' (its rate table is not in this workbook)")]
    return []


def resolve(facts, raters_dir):
    key = "go_digit"
    trace = []
    # The card only carries a Stand-alone TP grid. What applies depends on the
    # product: SAOD is OD-only (TP n/a, OD unratable here); a package is both
    # (neither ratable from a TP-only grid); SATP is the one we can resolve.
    if facts.policy_type == "saod":
        cites = _mapping_cites(key, raters_dir, facts.get("rto_code"))
        trace.append(TraceStep(
            "Policy is Stand-alone OD; the Go Digit card carries only a "
            "Stand-alone TP grid, so OD cannot be rated and TP does not exist "
            "for this cover.", None, cites[1] if cites else None))
        return (_unsupported("od", _GODIGIT_NO_OD + (_GODIGIT_POINTER if cites else ""),
                             cites),
                _na("tp", "Stand-alone Own Damage policy carries no third-party "
                          "cover, so no TP commission applies."),
                trace)
    if facts.policy_type == "comprehensive":
        cites = _mapping_cites(key, raters_dir, facts.get("rto_code"))
        trace.append(TraceStep(
            "Policy is a comprehensive package; the Go Digit card carries only a "
            "Stand-alone TP grid (no OD/package table), so neither component can "
            "be rated from it.", None, cites[0] if cites else None))
        return (_unsupported("od", _GODIGIT_NO_OD + (_GODIGIT_POINTER if cites else ""),
                             cites),
                _unsupported("tp", "This card only publishes a Stand-alone TP grid; a "
                             "package (OD+TP) TP rate is not available here. Insurer "
                             "cards in this bundle pay package commission on the OD "
                             "premium; the Stand-alone TP grid prices a different "
                             "product, so its rates do not apply to this policy's "
                             "TP leg.",
                             cites),
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
        fuel = facts.get("fuel")
        if fuel and fuel.lower() in ("electric", "ev"):
            # EVs have no engine cc and the grid carries no Electric rows at all.
            msg = ("The Go Digit '4W SATP' grid publishes no Electric segment "
                   "(only CNG/Petrol/Diesel), so an EV cannot be rated from this card.")
        elif fuel is None:
            msg = "No fuel type extracted; cannot pick a Go Digit fuel/cc segment."
        else:
            msg = f"No engine cc extracted; cannot split the '{fuel}' segment by cc."
        return od, _unsupported("tp", msg, [c1]), trace
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
