"""Single source of truth for the insurers this agent supports.

One entry per insurer, holding what the rest of the pipeline would otherwise
hard-code in four separate dicts: detection fingerprints, display name, and
rate-card path. The parser (extract.py) and resolver (grids/) keep their logic
keyed by the same `key`. Rebranding an insurer is a one-line fingerprint edit;
adding one is a new entry plus its parser, resolver and card.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Insurer:
    key: str
    name: str
    grid_file: str                  # path under raters/
    fingerprints: tuple[str, ...]   # regexes; first insurer to match a doc head wins


# Order matters: first match wins, so a competitor named in another insurer's
# boilerplate ("previous policy of TATA AIG" on an HDFC doc) can't steal it.
REGISTRY: tuple[Insurer, ...] = (
    Insurer("hdfc_ergo", "HDFC ERGO",
            "hdfc-ergo/feb-2025/Pvt Car New Grid Eff 1st Feb'25 (HDFC ergo) 1.pdf",
            (r"HDFC\s*ERGO",)),
    Insurer("go_digit", "Go Digit",
            "godigit/march-2026/Large Insurance Brokers Mar'26 - Shared.xlsx",
            (r"Go\s*Digit",)),
    Insurer("reliance", "Reliance",
            "reliance-indusind/feb-2026/Reliance Broking Premier  FEB 26 Grid.xlsx",
            # IndusInd Bank is the distribution partner on Reliance schedules;
            # its letterhead survives even when the watermark mangles "Reliance".
            (r"Reliance", r"IndusInd")),
    Insurer("tata_aig", "Tata AIG",
            "tata-aig/march-2026/Tata AIG Standard Grid_Communication_Mar'26_F_v2_0212.xlsx",
            (r"Tata\s*AIG",)),
)

_BY_KEY = {i.key: i for i in REGISTRY}


def name(key: str) -> str:
    return _BY_KEY[key].name


def grid_file(key: str) -> str:
    return _BY_KEY[key].grid_file
