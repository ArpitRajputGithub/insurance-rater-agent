"""FastAPI web layer: upload a policy PDF, rate it, show and persist the result.

A thin wrapper over insurance_rater.rate_policy -- no rating logic lives here.
Each upload is rated once and stored by content hash (see store.py), so prior
entries persist across restarts and re-uploads are served from storage.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from insurance_rater import ocr
from insurance_rater.agent import rate_policy

from . import store

_HERE = os.path.dirname(__file__)
RATERS_DIR = os.environ.get(
    "RATERS_DIR", os.path.join(os.path.dirname(_HERE), "bundle", "raters"))
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))

app = FastAPI(title="Insurance Rater")
app.mount("/static", StaticFiles(directory=os.path.join(_HERE, "static")), name="static")

# A cold or briefly-unreachable DB (e.g. Neon waking) shouldn't crash boot; the
# table is idempotently (re)created on the first request that reaches the DB.
try:
    store.init_db()
except Exception:
    pass

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # policy PDFs are a few MB; cap to protect the box

# Rating runs in a background thread and the browser polls /entry, so a slow
# upload (cold start, vision round-trips, a rate-limit wait) can't drop the POST
# and force a manual refresh. `_JOBS[digest]` is _PROCESSING while a rating runs,
# then an error string if it failed; success removes the key (result is in store).
# ponytail: in-memory map, fine on one worker; move to the DB if this ever scales
# past a single instance.
_PROCESSING = "processing"
_JOBS: dict[str, str] = {}


def _pending_state(digest: str) -> tuple[str, str | None]:
    """Classify a digest not yet in store: processing, error (with msg), or unknown."""
    job = _JOBS.get(digest)
    if job is None:
        return ("unknown", None)
    if job == _PROCESSING:
        return ("processing", None)
    return ("error", job)


def _run_job(tmp_path: str, filename: str, digest: str) -> None:
    try:
        result = rate_policy(tmp_path, RATERS_DIR).to_dict()
        result["policyFile"] = filename
        store.save(digest, filename, result)
        _JOBS.pop(digest, None)
    except Exception as exc:  # surface it on the poll page, don't loop forever
        _JOBS[digest] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _recent():
    # Never 500 a page over a transient DB hiccup; show an empty list instead.
    try:
        return store.list_recent()
    except Exception:
        return []


def _index(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        "index.html", {"request": request, "entries": _recent(), "error": error})


def _reject_reason(data: bytes) -> str | None:
    if len(data) > MAX_UPLOAD_BYTES:
        return f"File too large ({len(data) // (1024 * 1024)} MB); the limit is 25 MB."
    if b"%PDF-" not in data[:1024]:  # pdfplumber tolerates junk up to ~1KB before %PDF
        return "That doesn't look like a PDF. Please upload a motor-policy PDF."
    return None


def _assert_public(url: str) -> None:
    # SSRF guard: only fetch public http(s) hosts, never loopback/private/metadata IPs.
    # Ceiling: resolve-then-connect leaves a DNS-rebinding TOCTOU gap; pin the
    # validated IP into the connection if this ever fronts an internal network.
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("Could not read a host from that URL.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise ValueError("Could not resolve that host.")
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("That URL points to a non-public address; refused.")


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public(newurl)  # re-check each hop so a redirect can't bounce to a private host
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_URL_OPENER = urllib.request.build_opener(_GuardedRedirect())


def _fetch_url(url: str) -> bytes:
    _assert_public(url)
    req = urllib.request.Request(url, headers={"User-Agent": "insurance-rater/1.0"})
    try:
        with _URL_OPENER.open(req, timeout=15) as resp:
            return resp.read(MAX_UPLOAD_BYTES + 1)
    except (urllib.error.URLError, ValueError) as exc:
        raise ValueError(f"Could not fetch that URL: {getattr(exc, 'reason', exc)}")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _index(request)


@app.post("/rate", response_class=HTMLResponse)
async def rate(request: Request,
               file: UploadFile | None = File(None),
               url: str | None = Form(None),
               rerate: str | None = Form(None)):
    # Two dynamic-input paths: an uploaded file, or a URL we fetch server-side.
    if file is not None and file.filename:
        data = await file.read(MAX_UPLOAD_BYTES + 1)  # bounded read: don't slurp a huge upload
        filename = file.filename
    elif url and url.strip():
        try:
            data = _fetch_url(url.strip())
        except ValueError as exc:
            return _index(request, error=str(exc))
        filename = urlparse(url.strip()).path.rsplit("/", 1)[-1] or "policy.pdf"
    else:
        return _index(request, error="Choose a PDF or paste a link to a policy PDF.")
    reason = _reject_reason(data)
    if reason:
        return _index(request, error=reason)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    # Dispatch rating to a background thread and redirect to the poll page: the
    # browser never holds the long request, so a cold start or slow extraction
    # can't drop the response and force a manual refresh.
    digest = ocr._digest(tmp_path)
    # `rerate` skips the stored-result short-circuit so a result computed by
    # older code can be refreshed; store.save upserts, replacing the stale row.
    cached = store.get(digest) is not None and not rerate
    if cached or _JOBS.get(digest) == _PROCESSING:
        os.unlink(tmp_path)  # already rated, or a rating is already in flight
    else:
        _JOBS[digest] = _PROCESSING
        threading.Thread(target=_run_job, args=(tmp_path, filename, digest),
                         daemon=True).start()
    return RedirectResponse(f"/entry/{digest}", status_code=303)


@app.get("/entry/{digest}", response_class=HTMLResponse)
def entry(request: Request, digest: str):
    # An in-flight re-rate outranks the stored row, or the poll would render the
    # stale result it is about to replace.
    if _JOBS.get(digest) == _PROCESSING:
        return templates.TemplateResponse("processing.html", {"request": request})
    result = store.get(digest)
    if result is None:
        state, message = _pending_state(digest)
        if state == "processing":
            return templates.TemplateResponse("processing.html", {"request": request})
        if state == "error":
            _JOBS.pop(digest, None)  # shown once; let a re-upload retry
            return _index(request, error=message)
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "result.html",
        {"request": request, "r": result, "hash": digest, "cached": True})


if __name__ == "__main__":
    assert _reject_reason(b"%PDF-1.7\n1 0 obj") is None
    assert _reject_reason(b"not a pdf at all") is not None
    assert _reject_reason(b"") is not None
    assert _reject_reason(b"x" * (MAX_UPLOAD_BYTES + 1)) is not None
    for bad in ("file:///etc/passwd", "ftp://h/x", "http://127.0.0.1/x",
                "http://169.254.169.254/latest/meta-data/"):
        try:
            _assert_public(bad)
            raise AssertionError(f"should have refused {bad}")
        except ValueError:
            pass
    assert _pending_state("nope") == ("unknown", None)
    _JOBS["d"] = _PROCESSING
    assert _pending_state("d") == ("processing", None)
    _JOBS["d"] = "RuntimeError: boom"
    assert _pending_state("d") == ("error", "RuntimeError: boom")
    _JOBS.clear()
    print("upload-guard + ssrf + job-state self-check ok")
