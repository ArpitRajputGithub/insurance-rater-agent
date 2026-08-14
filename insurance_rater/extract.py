"""Policy-fact extraction: the fuzzy half of the pipeline.

Every supplied policy is a scanned, de-identified PDF, so we OCR it and pull
facts with tolerant regexes. This layer is allowed to be probabilistic and
could be backed by a vision-LLM extractor. It is isolated behind
`extract_policy()` so it can be swapped without touching the deterministic
grid resolvers downstream.

Each extracted fact carries a Citation back to the policy page it came from,
and a `confident` flag so genuine uncertainty (e.g. a fuel type the schedule
never prints) survives into the result instead of being silently guessed.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from . import insurers, ocr
from .models import Citation, PolicyFacts

# RTO state-code prefixes -> state name, used to normalise a location whose
# state the OCR mangled (e.g. "WwTTAR PRADESH"). Extend as new codes appear.
_STATE_BY_CODE = {
    "UP": "Uttar Pradesh", "DL": "Delhi", "HR": "Haryana", "MH": "Maharashtra",
    "KA": "Karnataka", "TN": "Tamil Nadu", "RJ": "Rajasthan", "GJ": "Gujarat",
    "MP": "Madhya Pradesh", "WB": "West Bengal", "PB": "Punjab", "AP": "Andhra Pradesh",
    "TS": "Telangana", "KL": "Kerala", "BR": "Bihar", "JH": "Jharkhand",
    "UK": "Uttarakhand", "HP": "Himachal Pradesh", "CH": "Chandigarh",
}


def _cite(source: str, page_idx: int, detail: str = "") -> Citation:
    return Citation(source=source, locator=f"page {page_idx + 1}", detail=detail)


def _find(pages: list[str], pattern: str, flags=re.I) -> Optional[tuple[re.Match, int]]:
    """First (match, page_index) across pages, or None."""
    rx = re.compile(pattern, flags)
    for i, text in enumerate(pages):
        m = rx.search(text)
        if m:
            return m, i
    return None


# Anchored on the schedule title, not a generic "Type of Cover" field: the Tata
# SATP fixture prints "Type of Cover: Package" on a Liability-Only policy.
_TITLE_COMP = re.compile(
    r"(?:Private Car|Auto Secure)\s*[-–]?\s*(?:Comprehensive|Package)\s+Policy", re.I)
_TITLE_SATP = re.compile(
    r"(?:Private Car|Auto Secure)\s*[-–]?\s*Liability Only Policy", re.I)
_TITLE_SAOD = re.compile(
    r"Stand[-\s]?alone\s+Own\s+Damage", re.I)


def _derive_type(pages: list[str]) -> str:
    """Policy type from the schedule title, then from content markers, else
    'unknown'. We never fall back to a per-insurer default: guessing a type the
    schedule never states just moves the error downstream into a confident
    wrong rate. 'unknown' makes the resolver refuse rather than assume."""
    joined = "\n".join(pages)
    if _TITLE_SAOD.search(joined):
        return "saod"
    if _TITLE_COMP.search(joined):
        return "comprehensive"
    if _TITLE_SATP.search(joined):
        return "satp"
    return _classify_policy(pages)


def _classify_policy(pages: list[str]) -> str:
    joined = "\n".join(pages)
    if re.search(r"liability only|third[\s-]party (cover|policy)|SATP|stand[\s-]alone", joined, re.I):
        if not re.search(r"package|comprehensive", joined, re.I):
            return "satp"
    if re.search(r"comprehensive|package policy", joined, re.I):
        return "comprehensive"
    # Fall back to SATP markers even if the word "package" appears in boilerplate.
    if re.search(r"liability only|third[\s-]party cover", joined, re.I):
        return "satp"
    return "unknown"


def detect_insurer(pages: list[str]) -> Optional[str]:
    head = "\n".join(pages[:2])
    for ins in insurers.REGISTRY:
        if any(re.search(fp, head, re.I) for fp in ins.fingerprints):
            return ins.key
    return None


def extract_policy(pdf_path: str) -> PolicyFacts:
    source = pdf_path.split("/")[-1]

    # Optional vision-LLM extractor (same PolicyFacts shape, grids untouched).
    # Opt-in via LLM_EXTRACT; it reads the page images directly, so it skips
    # Tesseract entirely. Any failure falls back to the OCR+regex path below.
    llm_error = None
    if os.environ.get("LLM_EXTRACT"):
        from . import llm
        try:
            pf = llm.extract(pdf_path, source)
            if pf is not None:
                return pf
        except Exception as e:  # network / rate-limit / parse error -> fall back to OCR
            # A free-tier 429 lands here too: we'd rather grind the OCR path (slow
            # but returns a result) than fail the request outright.
            llm_error = f"{type(e).__name__}: {e}"

    pages = ocr.page_texts(pdf_path)
    insurer_key = detect_insurer(pages)
    parser = _PARSERS.get(insurer_key)
    if parser is None:
        pf = PolicyFacts(insurer="unknown", policy_type=_classify_policy(pages))
        pf.warnings.append(f"Unrecognised insurer in {source}; no dedicated parser.")
        return pf
    pf = parser(pages, source)
    pf.insurer_key = insurer_key
    if llm_error:
        pf.warnings.append(f"LLM extraction failed ({llm_error}); used regex parser.")
    return pf


# ---------------------------------------------------------------------------
# Per-insurer parsers
# ---------------------------------------------------------------------------
def _num(pages, pattern, source):
    """First integer captured by `pattern` as (value, citation), or None."""
    r = _find(pages, pattern)
    if not r:
        return None
    m, i = r
    val = int(m.group(1).replace(",", "").split(".")[0])
    return val, _cite(source, i, m.group(0).strip())


def _parse_hdfc(pages: list[str], source: str) -> PolicyFacts:
    pf = PolicyFacts(insurer=insurers.name("hdfc_ergo"), policy_type=_derive_type(pages))
    # State drives the zone lookup; Gurgaon/HR schedule prints HARYANA.
    st = _find(pages, r"\b(HARYANA|DELHI|UTTAR PRADESH|PUNJAB|RAJASTHAN|MADHYA PRADESH|MAHARASHTRA|GUJARAT|KARNATAKA|KERALA|TAMIL ?NADU|WEST BENGAL|BIHAR|JHARKHAND|CHANDIGARH|UTTARAKHAND|HIMACHAL PRADESH|GOA|ODISHA|TELANGANA|ANDHRA PRADESH)\b")
    if st:
        m, i = st
        pf.add("rto_state", m.group(1).title(), _cite(source, i, m.group(0)))
    reg = _find(pages, r"\b([A-Z]{2}-?\d{1,2}-?[A-Z]{0,2}-?\d{0,4})\b")
    if reg:
        m, i = reg
        pf.add("registration", m.group(1), _cite(source, i, m.group(0)))
    mk = _find(pages, r"\b(MAHINDRA|MARUTI|HYUNDAI|TATA|RENAULT|HONDA|TOYOTA|KIA|SKODA|VOLKSWAGEN|FORD)\b")
    if mk:
        m, i = mk
        pf.add("make", m.group(1).title(), _cite(source, i))
    if (r := _num(pages, r"(?:Cubic Capacity|/?Watts)\D{0,10}(\d{3,4})", source)):
        pf.add("cc", *r)
    if (r := _num(pages, r"Year of Manufacture\D*(\d{4})", source)):
        pf.add("mfg_year", *r)
    # NCB present (a bonus % is deducted) -> NCB column of the grid.
    ncb = _find(pages, r"No Claim Bonus\s*\((\d{1,2})\s*%\)")
    if ncb:
        m, i = ncb
        pf.add("ncb_percent", int(m.group(1)), _cite(source, i, m.group(0)))
        pf.add("ncb_applies", True, _cite(source, i, m.group(0)))
    else:
        pf.add("ncb_applies", False, None, confident=False,
               note="No NCB deduction line found; assuming N-NCB.")
    if r := _num(pages, r"Net Own Damage Premium\s*\(a[}\)]\s*([\d,]+)", source):
        pf.add("od_premium", *r, note="Net OD premium.")
    elif r := _num(pages, r"Basic Own Damage\s*([\d,]+)", source):
        pf.add("od_premium", *r, note="Basic OD premium (Net OD not read).")
    # The HDFC slab footnote reads on comprehensive (package) GWP, not OD-only,
    # so the total package premium (a+b) is what drives the slab.
    if r := _num(pages, r"Total Package Premium\s*[({]a\+b[)}]\s*([\d,]+)", source):
        pf.add("package_premium", *r,
               note="Total Package Premium (a+b); HDFC slab is basis comprehensive GWP.")
    if r := _num(pages, r"Basic Third Party Liability\s*([\d,]+)", source):
        pf.add("tp_premium", *r)
    # Fuel is never printed on this schedule -> leave it explicitly unknown.
    pf.add("fuel", None, None, confident=False,
           note="Fuel type is not stated anywhere on the HDFC schedule.")
    return pf


def _parse_go_digit(pages: list[str], source: str) -> PolicyFacts:
    pf = PolicyFacts(insurer=insurers.name("go_digit"), policy_type=_derive_type(pages))
    reg = _find(pages, r"\b(UP|DL|HR|MH|KA|TN|RJ|GJ|MP|WB|PB|AP|TS|KL|BR|JH|UK|HP|CH)\s?\d{1,2}\s?[A-Z]{1,2}\s?\d{3,4}\b")
    if reg:
        m, i = reg
        raw = re.sub(r"\s", "", m.group(0))
        code = re.match(r"([A-Z]{2}\d{1,2})", raw).group(1)
        pf.add("registration", raw, _cite(source, i, m.group(0)))
        pf.add("rto_code", code, _cite(source, i, f"RTO code from registration {raw}"))
    # Town sits on the "RTO Location" line; the state next to it is OCR-mangled
    # ("WwTTAR PRADESH"), so normalise it from the RTO code prefix instead.
    loc = _find(pages, r"RTO Location\s*[=—–-]*\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)")
    if loc:
        m, i = loc
        town = m.group(1).strip()
        state = _STATE_BY_CODE.get((pf.get("rto_code") or "")[:2])
        value = f"{town}, {state}" if state else town
        pf.add("rto_location", value, _cite(source, i, m.group(0).strip()),
               note="State normalised from RTO code; OCR garbled it on the schedule."
               if state else "")
    mk = _find(pages, r"Make\s+([A-Z]{3,})")
    if mk:
        m, i = mk
        pf.add("make", m.group(1).title(), _cite(source, i))
    md = _find(pages, r"Variant \(Sub-Type\)\s+([A-Z0-9./ ]+)")
    if md:
        m, i = md
        pf.add("model", m.group(1).strip(), _cite(source, i))
    fu = _find(pages, r"Fuel Type\s+(Petrol|Diesel|CNG|LPG|Electric|EV)")
    if fu:
        m, i = fu
        pf.add("fuel", m.group(1).lower().replace("ev", "electric"), _cite(source, i, m.group(0)))
    if (r := _num(pages, r"Cubic Capacity\s+(\d{3,4})", source)):
        pf.add("cc", *r)
    mfg = _find(pages, r"Year of Mfg\.?\s+([\d-]+)")
    if mfg:
        m, i = mfg
        val = m.group(1)
        bad = val.startswith("0001")
        pf.add("mfg_year", val, _cite(source, i, m.group(0)), confident=not bad,
               note="Placeholder date 0001-01-01 in source; unusable." if bad else "")
    if (r := _num(pages, r"Year\s*of\s*Regn\.?\s+(\d{4})", source)):
        pf.add("regn_year", *r)
    return pf


def _parse_reliance(pages: list[str], source: str) -> PolicyFacts:
    pf = PolicyFacts(insurer=insurers.name("reliance"), policy_type=_derive_type(pages))
    reg = _find(pages, r"Registration No\.?\s+([A-Z]{2}\d{1,2}[A-Z]{1,2}\d{3,4})")
    if reg:
        m, i = reg
        raw = m.group(1)
        code = re.match(r"([A-Z]{2})(\d{1,2})", raw)
        pf.add("registration", raw, _cite(source, i, m.group(0)))
        pf.add("rto_code", f"{code.group(1)}-{code.group(2)}", _cite(source, i, f"RTO code from {raw}"))
    loc = _find(pages, r"RTO Location\s+([A-Za-z ]+-\s*[A-Za-z]+)")
    if loc:
        m, i = loc
        pf.add("rto_location", m.group(1).strip(), _cite(source, i, m.group(0).strip()))
    mm = _find(pages, r"Make / Model.*?\s(RENAULT|MARUTI|HYUNDAI|TATA|HONDA|TOYOTA|KIA)\s+([A-Z0-9. ]+?)\s+(?:CC|Cc|/ ?HP)")
    if mm:
        m, i = mm
        pf.add("make", m.group(1).title(), _cite(source, i))
        pf.add("model", m.group(2).strip().title(), _cite(source, i))
    if (r := _num(pages, r"(?:CC|Cc)\s*/\s*HP\s+(\d{3,4})", source)):
        pf.add("cc", *r)
    # The Reliance schedule prints no fuel field. Record what we do know (no
    # CNG/LPG kit fitted) and leave fuel unknown; the resolver decides the
    # Petrol/Bifuel-vs-Diesel column from this + cc under a documented rule.
    kit = _find(pages, r"CNG\s*/\s*LPG Kit\s*[=z]\s*([\d.,]+)")
    if kit:
        m, i = kit
        no_kit = float(m.group(1).replace(",", "")) == 0
        pf.add("cng_lpg_kit", not no_kit, _cite(source, i, m.group(0).strip()))
    pf.add("fuel", None, None, confident=False,
           note="Fuel type is not printed on the Reliance schedule.")
    ncb = _find(pages, r"Deduct\s+(\d{1,2})\s*%\s*for NCB")
    if ncb:
        m, i = ncb
        pf.add("ncb_percent", int(m.group(1)), _cite(source, i, m.group(0)))
        pf.add("ncb_applies", True, _cite(source, i, m.group(0)))
    if (r := _num(pages, r"TOTAL OWN DAMAGE PREMIUM\s*([\d,]+)", source)):
        pf.add("od_premium", *r)
    # OCR renders the closing ")" of "(TPPD 1)" as "}" on some passes, so accept both.
    if (r := _num(pages, r"Basic Liability \(TPPD[^)}]*[)}]\s*([\d,]+)", source)):
        pf.add("tp_premium", *r)
    return pf


def _parse_tata(pages: list[str], source: str) -> PolicyFacts:
    pf = PolicyFacts(insurer=insurers.name("tata_aig"), policy_type=_derive_type(pages))
    reg = _find(pages, r"Registration No\.?\s+([A-Z]{2}\s?\d{1,2}\s?[A-Z]{1,2}\s?\d{3,4})")
    if reg:
        m, i = reg
        raw = re.sub(r"\s", "", m.group(1))
        code = re.match(r"([A-Z]{2})(\d{1,2})", raw)
        pf.add("registration", raw, _cite(source, i, m.group(0)))
        pf.add("rto_code", code.group(1) + code.group(2),
               _cite(source, i, f"RTO code from registration {raw}"))
        state = _STATE_BY_CODE.get(code.group(1))
        if state:
            pf.add("rto_state", state,
                   _cite(source, i, f"state from RTO code {code.group(1)} ({raw})"))
    mm = _find(pages, r"Make\s*/\s*Model\s*/?\s*([A-Z]+)\s*/\s*([A-Z ]+?)\s*/")
    if mm:
        m, i = mm
        pf.add("make", m.group(1).title(), _cite(source, i))
        pf.add("model", m.group(2).strip().title(), _cite(source, i))
    bt = _find(pages, r"Body Type\s+([A-Za-z]+)")
    if bt:
        m, i = bt
        pf.add("body_type", m.group(1).upper(), _cite(source, i, m.group(0).strip()))
    # Business type (Renewal vs Rollover) hinges on who the previous insurer was.
    pi = _find(pages, r"Previous Insurance Details:.{0,120}?Name of the Insurer:\s*"
                      r"([A-Z][A-Za-z ]+?)(?=\s+Name of|\s*\n)", flags=re.I | re.S)
    if pi:
        m, i = pi
        pf.add("prev_insurer", m.group(1).strip(),
               _cite(source, i, f"Previous Insurance Details: {m.group(1).strip()}"))
    fu = (_find(pages, r"Fuel Type\s+(Petrol|Diesel|CNG|LPG|Electric|EV)\b")
          or _find(pages, r"Variant\s+[A-Z0-9 ]*\b(CNG|Petrol|Diesel|LPG|Electric)\b"))
    if fu:
        m, i = fu
        pf.add("fuel", m.group(1).upper() if m.group(1).upper() == "CNG" else m.group(1).lower(),
               _cite(source, i, m.group(0).strip()))
    if (r := _num(pages, r"\b(\d{3,4})\b\s*(?:CC)?\s*\n?\s*Make", source)):
        pf.add("cc", *r)
    if (r := _num(pages, r"Mfg\.?\s*Year\s+(\d{4})", source)):
        pf.add("mfg_year", *r)
    reg = _find(pages, r"Date of Registration\s+(\d{2}/\d{2}/\d{4})")
    if reg:
        m, i = reg
        pf.add("regn_date", m.group(1), _cite(source, i, m.group(0)))
        pf.add("regn_year", int(m.group(1)[-4:]), _cite(source, i, m.group(0)))
    rto = _find(pages, r"RTO Location\s+([A-Z][A-Za-z]+)")
    if rto:
        m, i = rto
        pf.add("rto_location", m.group(1).strip(), _cite(source, i, m.group(0).strip()))
    zn = _find(pages, r"Zone\s+([A-C])\b")
    if zn:
        m, i = zn
        pf.add("zone", m.group(1), _cite(source, i, m.group(0)))
    if (r := _num(pages, r"Basic TP premium\s*[^\d]{0,4}(\d{3,5})", source)):
        pf.add("tp_premium", *r)
    return pf


_PARSERS = {
    "hdfc_ergo": _parse_hdfc,
    "go_digit": _parse_go_digit,
    "reliance": _parse_reliance,
    "tata_aig": _parse_tata,
}
