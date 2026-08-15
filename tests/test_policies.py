"""End-to-end golden tests over the four supplied policies.

Each case asserts the resolved OD/TP rate (or the correct refusal) and that
the decision cites the exact grid cell that produced it -- the citation is the
product here, not a nice-to-have, so it is part of the assertion.

Extraction is vision-LLM only, so every case is a live Gemini call and needs
GEMINI_API_KEY. The default run covers the four supplied policies; set
RUN_CORPUS=1 to also pin the eight extra corpus policies (slower, more quota).
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
    # case-insensitive: OCR yields 'Haryana', the vision model 'HARYANA'
    assert "haryana -> zone-2" in _cites(r.od).lower()
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

# The eight extra corpus policies, pinned to the outcomes of the cell-verified
# full-corpus run (2026-08). Each row: od/tp -> (status, rate). A rate of None
# with RESOLVED means the component is honestly not applicable / not rateable
# as a number (e.g. SAOD TP), never a guessed zero.
_R, _U, _A = Status.RESOLVED, Status.UNSUPPORTED, Status.AMBIGUOUS
CORPUS = [
    ("Motor Policies/GOdigit 4W SAOD",  "Go Digit", "saod",          (_U, None), (_R, None)),
    ("Motor Policies/GoDigit 4W Comp",  "Go Digit", "comprehensive", (_U, None), (_U, None)),
    ("Motor Policies/Reliance 4W SAOD", "Reliance", "saod",          (_R, 20.0), (_R, None)),
    ("Motor Policies/Reliance 4w Comp", "Reliance", "comprehensive", (_A, None), (_R, 0.0)),
    ("Motor Policies/TATA 4W Comp",     "Tata AIG", "comprehensive", (_R, 0.0),  (_R, None)),
    ("Motor Policies/TATA 4W SAOD",     "Tata AIG", "saod",          (_R, 19.5), (_R, None)),
    ("godigit-4w-comp-019d1fe4-b6b1-73b8-9f98-cfdcbb013953", "Go Digit", "comprehensive",
     (_U, None), (_U, None)),
    ("godigit-4w-saod-019feaa7-a3e3-72ec-b29b-d99ea22f9c97", "Go Digit", "saod",
     (_U, None), (_R, None)),
]


@pytest.mark.skipif(not os.environ.get("RUN_CORPUS"),
                    reason="live LLM call per file; set RUN_CORPUS=1")
@pytest.mark.parametrize("name,insurer,ptype,od,tp",
                         CORPUS, ids=[c[0].split("/")[-1] for c in CORPUS])
def test_corpus_outcomes(name, insurer, ptype, od, tp):
    r = _run(name)
    assert r.insurer == insurer and r.policy_type == ptype
    assert (r.od.status, r.od.rate_percent) == od
    assert (r.tp.status, r.tp.rate_percent) == tp
