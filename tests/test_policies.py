"""End-to-end golden tests over the four supplied policies.

Each case asserts the resolved OD/TP rate (or the correct refusal) and that
the decision cites the exact grid cell that produced it -- the citation is the
product here, not a nice-to-have, so it is part of the assertion.

Extraction runs through OCR; results are cached under insurance_rater/.ocr_cache
so this suite is fast on repeat runs. A first run needs Tesseract installed.
"""
import os

import pytest

from insurance_rater.agent import rate_policy
from insurance_rater.models import Status

ROOT = os.path.dirname(os.path.dirname(__file__))
POLICIES = os.path.join(ROOT, "bundle", "sample-policies")
RATERS = os.path.join(ROOT, "bundle", "raters")


def _run(name):
    return rate_policy(os.path.join(POLICIES, f"{name}.pdf"), RATERS)


def _cites(component):
    return " || ".join(str(c) for c in component.citations)


def test_hdfc_od_resolved_tp_refused():
    """Comprehensive: OD resolves via zone+slab; TP is an honest refusal."""
    r = _run("pvt-car-comprehensive-hdfc-ergo")
    assert r.insurer == "HDFC ERGO"
    # OD: Haryana -> Zone-2; slab basis comprehensive premium 11,869 -> >10-50k;
    # petrol/non-petrol converge under NCB -> 17.5%
    assert r.od.applicable and r.od.status is Status.RESOLVED
    assert r.od.rate_percent == 17.5
    assert "Haryana -> Zone-2" in _cites(r.od)
    assert "Zone 2 · Package · slab >10-50k" in _cites(r.od)
    # TP: the grid has no TP table -> unsupported, not a guessed zero
    assert r.tp.applicable and r.tp.status is Status.UNSUPPORTED
    assert r.tp.rate_percent is None
    # A run with an unsupported component is not "resolved" overall
    assert r.status is Status.UNSUPPORTED


def test_go_digit_tp_only():
    """SATP: OD not applicable; TP from RTO cluster + fuel/cc segment."""
    r = _run("pvt-car-satp-go-digit")
    assert r.insurer == "Go Digit" and r.policy_type == "satp"
    assert not r.od.applicable and r.od.rate_percent is None      # never 0%
    assert r.tp.status is Status.RESOLVED and r.tp.rate_percent == 29.5
    assert "4W  RTO!C1609" in _cites(r.tp)                        # UP78 -> UP_Bad
    assert "4W SATP!E293" in _cites(r.tp)                         # Petrol>1000 -> 0.295
    assert r.status is Status.RESOLVED


def test_reliance_footnote_and_od_only_payout():
    """Comprehensive: OD via region + <1000cc footnote; TP paid on OD only (0%)."""
    r = _run("pvt-car-comprehensive-reliance")
    assert r.insurer == "Reliance"
    assert r.od.status is Status.RESOLVED and r.od.rate_percent == 17.5   # 22.5 - 5
    assert "RTO List!C1253" in _cites(r.od)                      # UP-16 -> Delhi
    assert "!C11" in _cites(r.od) and "!H3" in _cites(r.od)      # rate cell + footnote
    assert r.tp.status is Status.RESOLVED and r.tp.rate_percent == 0.0
    assert "!F11" in _cites(r.tp)                                # STP column = 0
    # fuel was assumed (not printed) -> confidence must not be "high"
    assert r.confidence.level == "medium"


def test_tata_tp_converges():
    """SATP: TP resolves because every non-new segment/business row agrees."""
    r = _run("pvt-car-satp-tata-aig")
    assert r.insurer == "Tata AIG" and r.policy_type == "satp"
    assert not r.od.applicable
    assert r.tp.status is Status.RESOLVED and r.tp.rate_percent == 38.0
    assert "Pvtcar!V" in _cites(r.tp)                            # DELHI column
    assert "rows 511-563" in _cites(r.tp)


@pytest.mark.parametrize("name", [
    "pvt-car-comprehensive-hdfc-ergo", "pvt-car-satp-go-digit",
    "pvt-car-comprehensive-reliance", "pvt-car-satp-tata-aig",
])
def test_every_fact_is_cited(name):
    """Every extracted fact with a value carries a citation."""
    r = _run(name)
    for key, f in r.facts.items():
        if f["value"] is not None:
            assert f["citation"], f"{name}: fact '{key}' has a value but no citation"
