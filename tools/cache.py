from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_CACHE_ROOT = Path("data/cache")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _make_key(s: str) -> str:
    """
    Make a stable cache key from an input string.
    """
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def get(key: str, fun: Callable[[], T], ttl: int) -> T:
    """
    Simple write-through cache API: get(key, fun, ttl)
    
    If key is available in cache and fresh (within ttl seconds), return cached value.
    Otherwise, execute fun(), store result in cache, and return it.
    
    Args:
        key: Cache key (will be hashed for filename)
        fun: Function to execute if cache miss or expired
        ttl: Time-to-live in seconds
        
    Returns:
        Cached value or result of fun()
    """
    cache_key = _make_key(key)
    cache_file = _CACHE_ROOT / f"{cache_key}.json"
    
    # Try to read from cache
    if cache_file.exists():
        try:
            raw = cache_file.read_text(encoding="utf-8")
            obj = json.loads(raw)
            ts = int(obj.get("ts", 0))
            now = int(time.time())
            if now - ts <= ttl:
                return obj["payload"]
        except Exception:
            pass  # Fall through to execute function
    
    # Cache miss or expired - execute function
    result = fun()
    
    # Store in cache
    _ensure_dir(_CACHE_ROOT)
    data = {
        "payload": result,
        "ts": int(time.time()),
        "ttl": ttl,
    }
    cache_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), 
        encoding="utf-8"
    )
    
    return result
