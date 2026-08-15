"""Core data models for the brokerage-rate agent.

Everything the agent produces is built from these dataclasses so the JSON
output has a single, stable shape. The design goal is that applicability,
evidence and uncertainty are explicit rather than buried in prose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Status(str, Enum):
    RESOLVED = "resolved"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"


@dataclass
class Citation:
    """A pointer back to the exact place a value came from.

    `source` is the file name. `locator` is granular: a PDF page ("page 1"),
    an xlsx range ("Rates!G22:H22"), or a table row. `detail` is human text.
    """
    source: str
    locator: str
    detail: str = ""

    def __str__(self) -> str:
        loc = f"{self.source} · {self.locator}"
        return f"{loc} — {self.detail}" if self.detail else loc


@dataclass
class Fact:
    """One extracted policy fact plus where it came from and how sure we are."""
    value: Any
    citation: Optional[Citation] = None
    confident: bool = True
    note: str = ""


@dataclass
class PolicyFacts:
    insurer: str
    policy_type: str                       # "comprehensive" | "satp" | "saod"
    insurer_key: Optional[str] = None      # resolver key, e.g. "go_digit"; None if unknown
    facts: dict[str, Fact] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        f = self.facts.get(key)
        return default if f is None else f.value

    def add(self, key: str, value: Any, citation: Optional[Citation] = None,
            confident: bool = True, note: str = "") -> None:
        self.facts[key] = Fact(value, citation, confident, note)


@dataclass
class ComponentRate:
    """OD or TP outcome. applicable=False means 'not applicable', never 0%."""
    component: str                         # "od" | "tp"
    applicable: bool
    status: Status
    rate_percent: Optional[float] = None
    citations: list[Citation] = field(default_factory=list)
    reason: str = ""


@dataclass
class TraceStep:
    decision: str
    policy_citation: Optional[Citation] = None
    grid_citation: Optional[Citation] = None


@dataclass
class Confidence:
    level: str                             # "high" | "medium" | "low"
    reason: str


@dataclass
class AgentResult:
    status: Status
    insurer: str
    policy_type: str
    facts: dict[str, Any]
    od: ComponentRate
    tp: ComponentRate
    trace: list[TraceStep]
    confidence: Confidence
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "insurer": self.insurer,
            "policyType": self.policy_type,
            "facts": self.facts,
            "rates": {
                "od": _component_json(self.od),
                "tp": _component_json(self.tp),
            },
            "trace": [
                {
                    "decision": s.decision,
                    "policyCitation": str(s.policy_citation) if s.policy_citation else None,
                    "gridCitation": str(s.grid_citation) if s.grid_citation else None,
                }
                for s in self.trace
            ],
            "confidence": {"level": self.confidence.level, "reason": self.confidence.reason},
            "warnings": self.warnings,
        }


def _component_json(c: ComponentRate) -> dict[str, Any]:
    return {
        "applicable": c.applicable,
        "status": c.status.value,
        "ratePercent": c.rate_percent,
        "reason": c.reason,
        "citations": [str(x) for x in c.citations],
    }
