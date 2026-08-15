"""Persistence for rated policies, keyed by file content hash.

A rating is expensive (OCR + grid lookup), so each result is stored under the
uploaded file's sha256; re-uploading the same file returns the stored result.
Backed by Postgres (DATABASE_URL) -- a managed DB such as Neon whose data
survives the container being wiped, so entries persist across restarts.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from typing import Optional

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL")

_CREATE = (
    "CREATE TABLE IF NOT EXISTS entries ("
    "hash TEXT PRIMARY KEY, filename TEXT, insurer TEXT, policy_type TEXT, "
    "status TEXT, created_at TIMESTAMPTZ, result_json TEXT NOT NULL)"
)
_UPSERT = (
    "INSERT INTO entries "
    "(hash, filename, insurer, policy_type, status, created_at, result_json) "
    "VALUES (%s, %s, %s, %s, %s, now(), %s) "
    "ON CONFLICT (hash) DO UPDATE SET filename=EXCLUDED.filename, "
    "insurer=EXCLUDED.insurer, policy_type=EXCLUDED.policy_type, "
    "status=EXCLUDED.status, created_at=EXCLUDED.created_at, "
    "result_json=EXCLUDED.result_json"
)


@contextlib.contextmanager
def _cursor():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            yield cur


def init_db() -> None:
    with _cursor() as cur:
        cur.execute(_CREATE)


def save(digest: str, filename: str, result: dict) -> None:
    with _cursor() as cur:
        cur.execute(_UPSERT, (
            digest, filename, result.get("insurer"), result.get("policyType"),
            result.get("status"), json.dumps(result)))


def get(digest: str) -> Optional[dict]:
    with _cursor() as cur:
        row = cur.execute(
            "SELECT result_json FROM entries WHERE hash = %s", (digest,)
        ).fetchone()
    return json.loads(row["result_json"]) if row else None


def list_recent(limit: int = 50) -> list[dict]:
    with _cursor() as cur:
        rows = cur.execute(
            "SELECT hash, filename, insurer, policy_type, status, created_at "
            "FROM entries ORDER BY created_at DESC LIMIT %s", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    if not DATABASE_URL:
        raise SystemExit("set DATABASE_URL to run the store self-check")
    init_db()
    h = "selfcheck-" + str(int(time.time()))
    r = {"insurer": "HDFC ERGO", "policyType": "comprehensive", "status": "resolved"}
    try:
        save(h, "selfcheck.pdf", r)
        assert get(h)["insurer"] == "HDFC ERGO"
        assert get("absent-" + h) is None
        save(h, "selfcheck.pdf", r)
        assert sum(e["hash"] == h for e in list_recent()) == 1
    finally:
        with _cursor() as cur:
            cur.execute("DELETE FROM entries WHERE hash = %s", (h,))
    print("store self-check ok")
