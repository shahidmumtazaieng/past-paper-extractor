"""
cache/cache_manager.py
=======================
Disk-based LRU cache for rendered PDF page images.

Why disk cache (not Redis)?
- Desktop app — no server infra needed on client machines
- diskcache is pure Python, zero config, persists across sessions
- Avoids re-rendering the same PDF page on every search
- Cache is keyed by (filepath + page_number + dpi) so it auto-invalidates
  if the same page is needed at different qualities

Cache Location: ~/.past_paper_extractor/cache/
Cache Limit: 2 GB (configurable)
"""

import os
import diskcache
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

_CACHE_DIR = str(Path.home() / ".past_paper_extractor" / "cache")
_CACHE_SIZE_LIMIT = 2 * 1024 ** 3   # 2 GB

# Module-level singleton cache instance
_cache: Optional[diskcache.Cache] = None


def get_cache() -> diskcache.Cache:
    global _cache
    if _cache is None:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        _cache = diskcache.Cache(
            _CACHE_DIR,
            size_limit=_CACHE_SIZE_LIMIT,
            eviction_policy="least-recently-used",
        )
        logger.info("Cache initialized at %s (limit=2GB)", _CACHE_DIR)
    return _cache


def make_page_key(filepath: str, page_number: int, dpi: int = 150) -> str:
    """Unique cache key for a rendered page."""
    return f"page::{filepath}::{page_number}::{dpi}"


def make_crop_key(filepath: str, page_number: int, bbox_str: str, dpi: int = 150) -> str:
    """Unique cache key for a cropped question region."""
    return f"crop::{filepath}::{page_number}::{bbox_str}::{dpi}"


def get_cached_page(filepath: str, page_number: int, dpi: int = 150) -> Optional[bytes]:
    """Return cached PNG bytes for a full page, or None."""
    key = make_page_key(filepath, page_number, dpi)
    return get_cache().get(key)


def set_cached_page(filepath: str, page_number: int, png_bytes: bytes, dpi: int = 150):
    """Store rendered page PNG bytes in cache."""
    key = make_page_key(filepath, page_number, dpi)
    get_cache().set(key, png_bytes, expire=None)   # No TTL — pages don't change


def get_cached_crop(filepath: str, page_number: int, bbox_str: str, dpi: int = 150) -> Optional[bytes]:
    key = make_crop_key(filepath, page_number, bbox_str, dpi)
    return get_cache().get(key)


def set_cached_crop(filepath: str, page_number: int, bbox_str: str, png_bytes: bytes, dpi: int = 150):
    key = make_crop_key(filepath, page_number, bbox_str, dpi)
    get_cache().set(key, png_bytes, expire=None)


def clear_cache():
    """Wipe entire cache (useful for troubleshooting)."""
    get_cache().clear()
    logger.info("Cache cleared")


def cache_stats() -> dict:
    """Return cache size info."""
    c = get_cache()
    return {
        "entries": len(c),
        "size_mb": round(c.volume() / 1024 ** 2, 1),
        "limit_mb": round(_CACHE_SIZE_LIMIT / 1024 ** 2, 1),
    }
