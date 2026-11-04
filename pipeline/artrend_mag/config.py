"""Shared paths and constants for the ARTREND magazine data pipeline.

All outputs live under ARTREND_magazine_data/. Existing ARTRENData assets are
read-only inputs; nothing in this package writes outside WORK_ROOT.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unicodedata
from pathlib import Path

WORK_ROOT = Path(__file__).resolve().parent.parent
ARTRENDATA = Path(os.environ.get("ARTRENDATA_ROOT") or WORK_ROOT.parent).resolve()

# ARTREND_SCRATCH=<name> redirects DB/raw/cache/runs to work/dev/<name>/ for parser development,
# so development runs never touch the production store.
_SCRATCH = os.environ.get("ARTREND_SCRATCH")
_BASE = WORK_ROOT / "work" / "dev" / _SCRATCH if _SCRATCH else WORK_ROOT
_BASE = _BASE.resolve()
_BASE.relative_to(WORK_ROOT)
DB_PATH = (_BASE / ("dev.sqlite" if _SCRATCH else "db/artrend_magazine.sqlite")).resolve()
RAW_ROOT = _BASE / "raw"
RUNS_ROOT = _BASE / "runs"
AUDIT_ROOT = WORK_ROOT / "work" / "audit"
OUTPUT_ROOT = WORK_ROOT / "outputs"
HTTP_CACHE = _BASE / "work_http_cache" if _SCRATCH else WORK_ROOT / "work" / "http_cache"

SCHEMA_VERSION = "2026-10-28.1"
CODE_VERSION = "0.2.0"
USER_AGENT = (
    "ARTREND-research-bot/0.1 (+art magazine research; "
    "contact via project owner) python-requests"
)
KST = dt.timezone(dt.timedelta(hours=9))


def configure_local_temporary_files() -> Path:
    path = (WORK_ROOT / "work" / "tmp").resolve()
    path.relative_to(WORK_ROOT)
    path.mkdir(parents=True, exist_ok=True)
    for name in ("TMPDIR", "TMP", "TEMP", "SQLITE_TMPDIR"):
        os.environ[name] = str(path)
    tempfile.tempdir = str(path)
    return path


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST).replace(microsecond=0)


def iso_now() -> str:
    return now_kst().isoformat()


def find_child(parent: Path, name: str) -> Path:
    """Resolve a child path whose on-disk Unicode normalization may differ (NFC/NFD)."""
    target = unicodedata.normalize("NFC", name)
    for child in parent.iterdir():
        if unicodedata.normalize("NFC", child.name) == target:
            return child
    raise FileNotFoundError(f"{name} not found under {parent}")


def v2v_root() -> Path:
    return find_child(ARTRENDATA, "아트랜드v2v")


def ro_sqlite_uri(path: Path) -> str:
    """Read-only, immutable URI so audits never create -wal/-shm or locks."""
    return f"file:{path.resolve()}?mode=ro&immutable=1"
