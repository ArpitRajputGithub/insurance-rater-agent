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
import time
import urllib.error
import urllib.request
from typing import Optional

from . import insurers, ocr
from .models import Citation, PolicyFacts

_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_MODEL = "qwen/qwen3.6-27b"          # Groq's vision model (image + JSON mode)
_RESOLUTION = 200  # DPI knob; qwen downscales past ~1.5-2MP, so crop-to-region is the next lever
_MAX_PAGES = 3     # bound the per-page vision loop; the schedule identifies in the first pages

_INT_KEYS = {"cc", "mfg_year", "regn_year", "ncb_percent",
             "od_premium", "tp_premium", "package_premium"}
_BOOL_KEYS = {"ncb_applies", "cng_lpg_kit"}
_SCHEMA_KEYS = [
    "registration", "rto_code", "rto_state", "rto_location", "make", "model",
    "fuel", "cc", "mfg_year", "regn_year", "ncb_percent", "ncb_applies",
    "od_premium", "tp_premium", "package_premium", "zone", "cng_lpg_kit",
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
    "Rules: rto_code = the registration's state letters + district digits, e.g. "
    "'HR51CQ0040' -> 'HR51'. The registration is safety-critical -- read it "
    "character by character. fuel lowercase (petrol/diesel/cng/lpg/electric). "
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
    # Several pages back-to-back can trip the free 8000 TPM; honour Retry-After
    # once, but cap the wait -- a full 60s sleep in a user-facing request reads as
    # a hang. If the limit needs longer, fail fast and let the caller surface it.
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.load(resp)
            return json.loads(payload["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(min(int(e.headers.get("retry-after", 5)), 15))
                continue
            raise


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
    if key == "rto_code" and insurer_key == "reliance":
        # Reliance's resolver keys off the dashed form "HR-51", not "HR51".
        m = re.match(r"([A-Z]{2})[-\s]?(\d{1,2})", str(value).upper())
        if m:
            return f"{m.group(1)}-{m.group(2)}"
    return value


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
    pf.warnings.append(f"Facts read from page images by vision model ({_MODEL}).")
    return pf


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
    if not available():
        raise SystemExit("set GROQ_API_KEY (or add it to .env) to run this")
    path = sys.argv[1]
    pf = extract(path, path.split("/")[-1])
    print("insurer:", pf.insurer, f"({pf.insurer_key})", "| type:", pf.policy_type)
    for k, fct in pf.facts.items():
        print(f"  {k} = {fct.value!r}  <- {fct.citation}")
