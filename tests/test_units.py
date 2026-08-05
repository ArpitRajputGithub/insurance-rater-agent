"""Pure-logic unit tests -- no OCR, no file I/O.

These lock the deterministic decisions that are easy to get subtly wrong:
premium-slab boundaries, segment banding, and the status roll-up precedence.
"""
from insurance_rater import grids
from insurance_rater.agent import _rollup
from insurance_rater.models import ComponentRate, Status


def _cr(component, applicable, status):
    return ComponentRate(component, applicable, status)


def test_hdfc_slab_boundaries():
    assert grids._hdfc_slab(0) == "<10k"
    assert grids._hdfc_slab(9_999) == "<10k"
    assert grids._hdfc_slab(10_000) == ">10-50k"      # boundary is exclusive-low
    assert grids._hdfc_slab(50_000) == ">50k-1L"
    assert grids._hdfc_slab(100_000) == ">1L-2L"
    assert grids._hdfc_slab(200_000) == ">2L"
    assert grids._hdfc_slab(5_000_000) == ">2L"


def test_go_digit_segment_banding():
    assert grids._godigit_segment("petrol", 999) == "Petrol<1000"
    assert grids._godigit_segment("petrol", 1000) == "Petrol>1000"
    assert grids._godigit_segment("diesel", 1499) == "Diesel<1500"
    assert grids._godigit_segment("diesel", 1500) == "Diesel>1500"
    assert grids._godigit_segment("cng", 900) == "CNG"
    assert grids._godigit_segment(None, 1000) is None       # unknown fuel -> no guess


def test_rollup_precedence():
    R, U, A = Status.RESOLVED, Status.UNSUPPORTED, Status.AMBIGUOUS
    # not-applicable OD (TP-only policy) is ignored in the roll-up
    assert _rollup(_cr("od", False, R), _cr("tp", True, R)) is R
    # a single unsupported applicable component pulls the whole run to unsupported
    assert _rollup(_cr("od", True, R), _cr("tp", True, U)) is U
    # ambiguous outranks unsupported
    assert _rollup(_cr("od", True, A), _cr("tp", True, U)) is A
