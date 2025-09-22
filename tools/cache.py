from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Tuple

CACHE_ROOT = Path("data/.cache")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def make_key(s: str) -> str:
    """
    Make a stable cache key from an input string.
    """
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _cache_file(kind: str, key: str) -> Path:
    d = CACHE_ROOT / kind
    _ensure_dir(d)
    return d / f"{key}.json"


def write_cache(kind: str, key: str, payload: Any, ttl_s: int) -> Path:
    """
    Write a cache entry with payload and metadata.
    """
    path = _cache_file(kind, key)
    data = {
        "payload": payload,
        "meta": {
            "ts": int(time.time()),
            "ttl_s": int(ttl_s),
            "version": 1,
        },
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_cache(kind: str, key: str, ttl_s: int) -> Tuple[Any | None, dict | None]:
    """
    Return (payload, meta) if fresh, else (None, meta_or_none).
    """
    path = _cache_file(kind, key)
    if not path.exists():
        return None, None
    try:
        raw = path.read_text(encoding="utf-8")
        obj = json.loads(raw)
        meta = obj.get("meta") or {}
        ts = int(meta.get("ts", 0))
        now = int(time.time())
        ttl = int(ttl_s or meta.get("ttl_s", 0))
        if now - ts <= ttl:
            return obj.get("payload"), meta
        return None, meta
    except Exception:
        return None, None
