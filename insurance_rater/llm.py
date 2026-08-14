"""LLM-backed policy extraction (optional, Groq vision).

The regex parsers in extract.py read Tesseract's OCR text, which loses faint or
noisy fields -- a de-identified registration plate can come out garbled in
every pass, and a title the patterns don't anticipate (Stand-alone Own Damage)
is misread. This module reads the rendered page *images* directly with a
vision model and returns the same PolicyFacts shape the deterministic grid
resolvers consume, so it replaces both the OCR and the regex stages in one
call. Every field still carries a Citation (page + what the model read), so an
LLM-sourced fact stays auditable.

Opt-in: used only when LLM_EXTRACT is set and GROQ_API_KEY is available;
extract_policy() falls back to the Tesseract+regex path otherwise or on any
error. Grids never call an LLM -- rates always come from a cited grid cell.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.request
from typing import Optional

from . import insurers, ocr
from .models import Citation, PolicyFacts

_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_MODEL = "qwen/qwen3.6-27b"          # Groq's vision model (image + JSON mode)
_RESOLUTION = 200  # DPI knob; qwen downscales past ~1.5-2MP, so crop-to-region is the next lever
_MAX_PAGES = 4     # bound the per-page vision loop; Tata's vehicle table sits on page 4

_INT_KEYS = {"cc", "mfg_year", "regn_year", "ncb_percent",
             "od_premium", "tp_premium", "package_premium"}
_BOOL_KEYS = {"ncb_applies", "cng_lpg_kit"}
# rto_code is deliberately absent: it is derived from `registration` in code
# (see _rto_from_registration), never transcribed by the model. Asking the model
# for it made it read the plate's two state letters twice -- once here, once in
# `registration` -- and a single misread (UP->UF) then broke the RTO lookup.
_SCHEMA_KEYS = [
    "registration", "rto_state", "rto_location", "make", "model",
    "fuel", "cc", "mfg_year", "regn_year", "ncb_percent", "ncb_applies",
    "od_premium", "tp_premium", "package_premium", "zone", "cng_lpg_kit",
    "body_type", "prev_insurer",
]

_SYSTEM = (
    "You read the page images of an Indian motor-insurance policy schedule and "
    "return ONLY a JSON object.\n"
    "Keys:\n"
    "  insurer: one of 'hdfc_ergo', 'go_digit', 'reliance', 'tata_aig', or "
    "'unknown'.\n"
    "  policy_type: exactly one of 'comprehensive', 'satp', 'saod'. Decide from "
    "the SCHEDULE TITLE, never a 'Type of Cover' field. Title says 'Package' or "
    "'Comprehensive' -> comprehensive; 'Liability Only' or 'Stand-alone TP' -> "
    "satp; 'Stand-alone Own Damage' -> saod.\n"
    "  fields: an object mapping any of these keys you can read to "
    "{\"value\":..., \"page\":<1-based int>, \"quote\":\"the text you read\"}. "
    "Allowed keys: " + ", ".join(_SCHEMA_KEYS) + ".\n"
    "Rules: read the full registration plate character by character -- it is "
    "safety-critical and drives the RTO lookup; do not abbreviate it. Put the "
    "RTO's state name from the 'RTO Location' line into rto_state (e.g. 'UTTAR "
    "PRADESH'). fuel lowercase (petrol/diesel/cng/lpg/electric). "
    "cc, mfg_year, regn_year, ncb_percent and *_premium as integers. "
    "ncb_applies and cng_lpg_kit are booleans (true/false), not header text. "
    "Omit any field you cannot read. Never guess a value."
)

_loaded_env = False


def _load_env() -> None:
    """Populate os.environ from the repo .env once (no python-dotenv dep)."""
    global _loaded_env
    if _loaded_env:
        return
    _loaded_env = True
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def _api_key() -> Optional[str]:
    _load_env()
    return os.environ.get("GROQ_API_KEY")


def available() -> bool:
    return bool(_api_key())


def _encode(image) -> str:
    """PIL image -> greyscale PNG data URL (greyscale keeps the request small)."""
    buf = io.BytesIO()
    image.convert("L").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _call(data_urls: list[str]) -> dict:
    content = [{"type": "text", "text": "Extract the fields as instructed."}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in data_urls]
    body = {
        "model": _MODEL,
        "temperature": 0,
        "reasoning_effort": "none",  # qwen3 is a thinking model; without this it
                                     # spends the budget reasoning and returns an
                                     # empty body that fails JSON-mode validation
        "response_format": {"type": "json_object"},
        "max_tokens": 1500,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": content},
        ],
    }
    req = urllib.request.Request(
        _ENDPOINT, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "insurance-rater/1.0",  # Groq's edge 403s urllib's default UA
                 "Authorization": f"Bearer {_api_key()}"})
    # Let a 429 (free-tier TPM) propagate: extract_policy catches it and falls
    # back to the OCR path -- slower, but the request still returns a result.
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.load(resp)
    return json.loads(payload["choices"][0]["message"]["content"])


def _insurer_key(value) -> Optional[str]:
    s = str(value or "").strip().lower()
    for ins in insurers.REGISTRY:
        if s == ins.key or s == ins.name.lower():
            return ins.key
    for ins in insurers.REGISTRY:  # loose: "go digit general insurance"
        if ins.name.lower() in s or ins.key.replace("_", " ") in s:
            return ins.key
    return None


def _coerce(key: str, value, insurer_key: Optional[str]):
    if key in _INT_KEYS:
        try:
            return int(str(value).replace(",", "").split(".")[0])
        except (ValueError, TypeError):
            return value
    if key in _BOOL_KEYS:
        # Model sometimes returns a header ("Current Policy") whose truthiness would
        # flip HDFC to the NCB rate; map real yes/no only, else None.
        s = str(value).strip().lower()
        if s in ("true", "yes", "y", "1", "applicable", "applied"):
            return True
        if s in ("false", "no", "n", "0", "not applicable", "na", "none"):
            return False
        return None
    if key == "fuel":
        return str(value).strip().lower()
    return value


def _rto_from_registration(reg, insurer_key: Optional[str]) -> Optional[str]:
    """Derive the RTO code (state letters + district digits) from the raw plate.

    Mirrors the OCR path (see extract.py): rto_code is never read on its own,
    only derived from `registration`, so one transcription is the single source
    of truth. Reliance's RTO List keys on the dashed form 'UP-16'; others plain.
    """
    m = re.match(r"([A-Za-z]{2})[-\s]?(\d{1,2})", str(reg).replace(" ", ""))
    if not m:
        return None
    sep = "-" if insurer_key == "reliance" else ""
    return f"{m.group(1).upper()}{sep}{m.group(2)}"


def _build(raw: dict, source: str) -> PolicyFacts:
    key = _insurer_key(raw.get("insurer"))
    ptype = raw.get("policy_type") or "unknown"  # never guess; resolver refuses
    pf = PolicyFacts(insurer=insurers.name(key) if key else "unknown",
                     policy_type=ptype, insurer_key=key)
    for field_key, obj in (raw.get("fields") or {}).items():
        if field_key not in _SCHEMA_KEYS or not isinstance(obj, dict):
            continue
        value = obj.get("value")
        if value is None or value == "":
            continue
        cite = None
        if obj.get("page"):
            cite = Citation(source, f"page {obj['page']}",
                            str(obj.get("quote", "")).strip())
        pf.add(field_key, _coerce(field_key, value, key), cite)
    reg_f = pf.facts.get("registration")
    if reg_f and reg_f.value:
        code = _rto_from_registration(reg_f.value, key)
        if code:
            loc = reg_f.citation.locator if reg_f.citation else ""
            pf.add("rto_code", code,
                   Citation(source, loc, f"RTO code from registration {reg_f.value}"))
    _reconcile_rto(pf)
    pf.warnings.append(f"Facts read from page images by vision model ({_MODEL}).")
    return pf


def _reconcile_rto(pf: PolicyFacts) -> None:
    """Prefer the reliably-read RTO *prose* over the plate's two state letters.

    The RTO's state is printed twice on the schedule: as dense plate glyphs
    (error-prone) and as clean text on the 'RTO Location' line. rto_code's state
    prefix is derived from the plate, so a vision misread (UP -> UF, or even a
    valid-but-wrong DL) breaks the exact-match RTO lookup. When rto_state /
    rto_location names a state we recognise and its code disagrees with the
    plate's prefix, trust the prose and keep only the plate's district digits --
    the digits read far more reliably than the two letters. Prose and plate name
    the same RTO, so a disagreement means one was misread; the prose wins.
    """
    from .extract import _STATE_BY_CODE  # code -> state name; invert for lookup
    code_f = pf.facts.get("rto_code")
    if not code_f:
        return
    m = re.match(r"([A-Za-z]{2})([-\s]?)(\d{1,2})", str(code_f.value))
    if not m:
        return
    prefix, sep, digits = m.group(1).upper(), m.group(2), m.group(3)
    prose = " ".join(str(pf.get(k) or "") for k in ("rto_state", "rto_location")).lower()
    want = next((c for name, c in
                 {v.lower(): k for k, v in _STATE_BY_CODE.items()}.items()
                 if name in prose), None)
    if not want or want == prefix:
        return
    old = code_f.value
    code_f.value = f"{want}{sep}{digits}"
    code_f.note = (f"{code_f.note}; " if code_f.note else "") + (
        f"plate prefix '{prefix}' disagrees with the RTO location text; used "
        f"state code '{want}' from the schedule (was {old!r})")


def _merge(merged: dict, raw: dict, page: int) -> None:
    """Fold one page's raw extraction into the accumulator; first value wins.

    The model sees a single image per call, so its own "page" is always 1 --
    we overwrite it with the true page index so citations point at the real page.
    """
    if not merged.get("insurer") and str(raw.get("insurer") or "").lower() not in ("", "unknown"):
        merged["insurer"] = raw["insurer"]
    if not merged.get("policy_type") and raw.get("policy_type"):
        merged["policy_type"] = raw["policy_type"]
    for k, obj in (raw.get("fields") or {}).items():
        if k in merged["fields"] or not isinstance(obj, dict) or obj.get("value") in (None, ""):
            continue
        merged["fields"][k] = {**obj, "page": page}


def _has_core(merged: dict) -> bool:
    """Schedule identified and its core vehicle fields read -> later pages are
    boilerplate (T&C, IDV tables), so we can stop. cc + an RTO id sit on the
    schedule's first page for all four insurers; fuel is deliberately excluded
    (some cards never print it, so requiring it would read every page in vain)."""
    f = merged["fields"]
    has_rto = any(k in f for k in ("rto_code", "rto_location", "rto_state"))
    return bool(merged.get("insurer") and merged.get("policy_type") and has_rto and "cc" in f)


def extract(pdf_path: str, source: str) -> Optional[PolicyFacts]:
    """Vision-extract facts from the PDF, or None if no API key is configured.

    One request per page (fits the free tier's per-minute budget), merged so a
    field on page 2+ is not lost; early-stop once core fields are in hand.
    ponytail: per-page loses cross-page context; a paid tier sends the whole doc.
    """
    if not available():
        return None
    merged = {"insurer": None, "policy_type": None, "fields": {}}
    for i, im in enumerate(ocr.render_pages(pdf_path, _RESOLUTION), 1):
        _merge(merged, _call([_encode(im)]), i)
        # The schedule that identifies the policy sits in the first pages for all
        # four insurers; without this cap a doc that never yields `cc` (unreadable
        # or unprinted) would grind every page -- 12-15 sequential vision calls.
        if _has_core(merged) or i >= _MAX_PAGES:
            break
    return _build(merged, source)


if __name__ == "__main__":  # manual: python -m insurance_rater.llm <policy.pdf>
    import sys
    # Offline self-check: derive rto_code from the plate, then reconcile against
    # the RTO prose (no network / API key needed).
    _pf = PolicyFacts(insurer="Reliance", policy_type="comprehensive", insurer_key="reliance")
    _pf.add("registration", "UF16CS5830")   # vision misread of UP16CS5830 (P->F)
    _pf.add("rto_state", "UTTAR PRADESH")
    _pf.add("rto_code", _rto_from_registration("UF16CS5830", "reliance"))
    assert _pf.facts["rto_code"].value == "UF-16", _pf.facts["rto_code"].value
    _reconcile_rto(_pf)                      # prose "UTTAR PRADESH" wins over "UF"
    assert _pf.facts["rto_code"].value == "UP-16", _pf.facts["rto_code"].value
    # a correctly-read plate (plain go_digit form) is left untouched
    _pf2 = PolicyFacts(insurer="Go Digit", policy_type="comprehensive", insurer_key="go_digit")
    _pf2.add("rto_state", "UTTAR PRADESH")
    _pf2.add("rto_code", _rto_from_registration("UP16CS5830", "go_digit"))
    _reconcile_rto(_pf2)
    assert _pf2.facts["rto_code"].value == "UP16", _pf2.facts["rto_code"].value
    print("rto derive+reconcile self-check ok")
    if not available():
        raise SystemExit("set GROQ_API_KEY (or add it to .env) to run this")
    path = sys.argv[1]
    pf = extract(path, path.split("/")[-1])
    print("insurer:", pf.insurer, f"({pf.insurer_key})", "| type:", pf.policy_type)
    for k, fct in pf.facts.items():
        print(f"  {k} = {fct.value!r}  <- {fct.citation}")
