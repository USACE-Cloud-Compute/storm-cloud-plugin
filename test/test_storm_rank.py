"""Unit tests for storm rank / DSS filename derivation.

Regression guard: DSS files and grid blocks must be named by the storm's true
catalog rank (por_rank, encoded as the STAC item id), not the enumeration
position of get_all_items() (which is not rank-sorted). Mislabeling both
misnames files and, because the name is the idempotency key, makes re-runs
accumulate orphan duplicates.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from actions import dss_filename, parse_storm_datetime, storm_rank  # noqa: E402


class _Item:
    def __init__(self, item_id, dt=None):
        self.id = item_id
        self.datetime = dt


def test_uses_item_id_not_enumeration_index():
    # The 3rd item returned by get_all_items() can be por_rank 441.
    assert storm_rank(_Item("441"), fallback=3) == 441


def test_falls_back_for_non_numeric_id():
    # storm_search uses a %Y-%m-%dT%H id when searched without a rank.
    assert storm_rank(_Item("1982-06-07T06"), fallback=7) == 7


def test_falls_back_for_none_id():
    assert storm_rank(_Item(None), fallback=12) == 12


def test_filename_encodes_true_rank():
    # por_rank 441 -> r441, never r003 (its enumeration position).
    rank = storm_rank(_Item("441"), fallback=3)
    assert dss_filename(datetime(1982, 6, 7, 6), rank, 72) == "19820607_72hr_st1_r441.dss"


def test_parse_datetime_from_legacy_id():
    assert parse_storm_datetime(_Item("1982-06-07T06")) == datetime(1982, 6, 7, 6)


def test_parse_datetime_from_item_datetime_for_rank_id():
    dt = datetime(1982, 6, 7, 6)
    # Rank-keyed id ("441") isn't a datetime; fall back to item.datetime.
    assert parse_storm_datetime(_Item("441", dt=dt)) == dt


def test_parse_datetime_none_id_does_not_raise():
    # A None id makes strptime raise TypeError, not ValueError; parse must
    # tolerate it and fall through to item.datetime rather than crash the loop.
    # tz-aware item.datetime is normalized to tz-naive UTC (see below).
    dt = datetime(1982, 6, 7, 6, tzinfo=timezone.utc)
    result = parse_storm_datetime(_Item(None, dt=dt))
    assert result == datetime(1982, 6, 7, 6)
    assert result.tzinfo is None
    assert parse_storm_datetime(_Item(None)) is None


def test_parse_datetime_returns_tz_naive_utc():
    # pystac item.datetime is tz-aware; AORC's zarr time coord is tz-naive, so a
    # tz-aware bound raises "Cannot compare tz-naive and tz-aware ..." when
    # slicing in convert-to-dss. parse_storm_datetime must return tz-naive UTC.
    dt = datetime(1982, 6, 7, 6, tzinfo=timezone(timedelta(hours=5)))  # 06:00+05:00
    result = parse_storm_datetime(_Item("441", dt=dt))
    assert result == datetime(1982, 6, 7, 1)  # 01:00 UTC, naive
    assert result.tzinfo is None


def test_producers_derive_identical_filenames():
    """Lockstep invariant: convert_to_dss (writes the DSS) and create_grid_file
    (must locate that same DSS) have to agree on the filename byte-for-byte.
    Both now derive it via the single ``dss_filename`` helper, so re-run the
    exact derivation each loop performs and assert one shared result. The
    source guard below keeps them from re-inlining a divergent format string.
    """
    item = _Item("441", dt=datetime(1982, 6, 7, 6))
    idx, duration = 3, 72

    def derive(it, i):
        start = parse_storm_datetime(it)
        return dss_filename(start, storm_rank(it, i), duration)

    # Simulate both producer loops over the same item at the same position.
    convert_name = derive(item, idx)
    grid_name = derive(item, idx)
    assert convert_name == grid_name == "19820607_72hr_st1_r441.dss"


def test_neither_producer_reinlines_the_format():
    """Drift guard: the ``…hr_st1_r…`` format must live only in dss_filename.
    If a producer re-inlines it, the two can diverge without any test noticing.
    """
    for name in ("convert_to_dss.py", "create_grid_file.py"):
        source = (SRC / "actions" / name).read_text()
        assert "hr_st1_r" not in source, f"{name} re-inlines the DSS format; call dss_filename()"
