"""Shared helpers for the per-insurer grid resolvers.

Rate-card file locations, workbook loading, citation builders, and the two
component constructors (`_na` / `_unsupported`) every resolver returns. Nothing
here is specific to one insurer's card -- that logic lives in the sibling
modules (go_digit, hdfc, reliance, tata).
"""
from __future__ import annotations

import os
import warnings

import openpyxl
from openpyxl.utils import get_column_letter

from .. import insurers
from ..models import Citation, ComponentRate, Status


def grid_path(insurer_key: str, raters_dir: str) -> str:
    return os.path.join(raters_dir, insurers.grid_file(insurer_key))


def _source(insurer_key: str) -> str:  # basename doubles as the citation source
    return os.path.basename(insurers.grid_file(insurer_key))


def _wb(insurer_key: str, raters_dir: str):
    # Suppress openpyxl's warning about an embedded image; it does not affect cell values.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(grid_path(insurer_key, raters_dir), data_only=True)


def _xls_cite(insurer_key, sheet, row, col, detail):
    loc = f"{sheet}!{get_column_letter(col)}{row}"
    return Citation(source=_source(insurer_key), locator=loc, detail=detail)


def _na(component: str, reason: str) -> ComponentRate:
    """Component that does not exist for this policy (never 0%)."""
    return ComponentRate(component=component, applicable=False,
                         status=Status.RESOLVED, rate_percent=None, reason=reason)


def _unsupported(component: str, reason: str, citations=None) -> ComponentRate:
    return ComponentRate(component=component, applicable=True,
                         status=Status.UNSUPPORTED, rate_percent=None,
                         reason=reason, citations=citations or [])
