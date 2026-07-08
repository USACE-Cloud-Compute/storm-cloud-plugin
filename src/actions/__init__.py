"""Storm-cloud plugin actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_storm_datetime(item: Any) -> datetime | None:
    """Storm start datetime for a STAC item, or None if unparseable.

    Older catalogs use a ``%Y-%m-%dT%H`` item id; newer ones use the por_rank as
    the id and carry the datetime on ``item.datetime``.
    """
    try:
        return datetime.strptime(item.id, "%Y-%m-%dT%H")
    except (TypeError, ValueError):
        # ValueError: id is a por_rank (e.g. "441"), not a datetime.
        # TypeError: id is None. Both fall through to item.datetime.
        return item.datetime if getattr(item, "datetime", None) else None


def storm_rank(item: Any, fallback: int) -> int:
    """Return a storm item's catalog rank (por_rank).

    storm_search encodes por_rank as the item id (``item_id = f"{por_rank}"``),
    so the true rank is ``int(item.id)``. get_all_items() is NOT rank-sorted, so
    the enumeration index mislabels files (e.g. por_rank 441 named r003) and,
    because names are the idempotency key, re-runs accumulate orphan duplicates.
    Fall back to ``fallback`` only when the id is not a plain rank integer (e.g.
    the ``%Y-%m-%dT%H`` id used when a storm is searched without a rank).
    """
    try:
        return int(item.id)
    except (TypeError, ValueError):
        return fallback


def dss_filename(storm_start: datetime, rank: int, storm_duration: Any) -> str:
    """Canonical DSS filename for a storm.

    convert_to_dss (producer) and create_grid_file (which must find that same
    file) both derive names here, so the two stay in lockstep — any drift would
    silently mis-pair storms with DSS files.
    """
    date_str = storm_start.strftime("%Y%m%d")
    return f"{date_str}_{storm_duration}hr_st1_r{rank:03d}.dss"
