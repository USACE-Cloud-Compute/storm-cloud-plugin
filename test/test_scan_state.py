"""Unit tests for scan_state — the durable/validated resume guards."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import scan_state  # noqa: E402

_HEADER = "storm_date,min,mean,max,x,y"
_ROW1 = "1979-02-01T00,0.0,1.2,9.9,-100.0,40.0"
_ROW2 = "1979-02-02T00,0.1,1.3,9.8,-100.0,40.0"


def _params(**over):
    base = {
        "start_date": "1979-02-01",
        "end_date": "1979-03-01",
        "storm_duration": 72,
        "min_precip_threshold": 0.0,
        "top_n_events": 10,
        "check_every_n_hours": 24,
        "num_workers": 3,  # deliberately NOT part of the fingerprint
        "specific_dates": [],
    }
    base.update(over)
    return base


# --- fingerprint -----------------------------------------------------------


def test_fingerprint_ignores_non_scan_params():
    # num_workers must not affect reuse — it's an execution knob, not a scan input.
    assert scan_state.fingerprint(_params(num_workers=3)) == scan_state.fingerprint(
        _params(num_workers=8)
    )


def test_fingerprint_changes_with_scan_params():
    assert scan_state.fingerprint(_params(storm_duration=72)) != scan_state.fingerprint(
        _params(storm_duration=24)
    )


def test_fingerprint_specific_dates_order_insensitive():
    a = scan_state.fingerprint(_params(specific_dates=["2001-01-01", "2002-02-02"]))
    b = scan_state.fingerprint(_params(specific_dates=["2002-02-02", "2001-01-01"]))
    assert a == b


def test_params_match_roundtrip(tmp_path):
    scan_state.write_fingerprint(tmp_path, _params())
    assert scan_state.params_match(tmp_path, _params())
    assert scan_state.params_match(tmp_path, _params(num_workers=99))  # knob ignored
    assert not scan_state.params_match(tmp_path, _params(top_n_events=5))


def test_params_match_false_when_no_fingerprint(tmp_path):
    assert not scan_state.params_match(tmp_path, _params())


# --- completion sentinel ---------------------------------------------------


def test_completion_sentinel(tmp_path):
    assert not scan_state.is_marked_complete(tmp_path)
    scan_state.mark_complete(tmp_path)
    assert scan_state.is_marked_complete(tmp_path)


# --- quarantine ------------------------------------------------------------


def test_quarantine_moves_not_deletes(tmp_path):
    d = tmp_path / "cat"
    d.mkdir()
    (d / "keep.txt").write_text("data")
    dest = scan_state.quarantine(d)
    assert dest is not None
    assert not d.exists()
    assert (dest / "keep.txt").read_text() == "data"  # nothing destroyed


def test_quarantine_missing_is_noop(tmp_path):
    assert scan_state.quarantine(tmp_path / "nope") is None


def test_quarantine_multiple_no_collision(tmp_path):
    for _ in range(3):
        (tmp_path / "cat").mkdir()
        assert scan_state.quarantine(tmp_path / "cat") is not None
    quarantined = sorted(p.name for p in tmp_path.iterdir())
    assert quarantined == ["cat.quarantine-1", "cat.quarantine-2", "cat.quarantine-3"]


# --- CSV repair / validation ----------------------------------------------


def _csv(tmp_path, body):
    p = tmp_path / "storm-stats.csv"
    p.write_text(body, encoding="utf-8")
    return p


def test_repair_accepts_clean_csv_untouched(tmp_path):
    p = _csv(tmp_path, "\n".join([_HEADER, _ROW1, _ROW2]) + "\n")
    before = p.read_text()
    assert scan_state.repair_partial_csv(p) is True
    assert p.read_text() == before  # no rewrite when already clean


def test_repair_drops_torn_final_line(tmp_path):
    # Pod killed mid-write: last row missing columns.
    p = _csv(tmp_path, "\n".join([_HEADER, _ROW1, "1979-02-02T00,0.1,1.3"]) )
    assert scan_state.repair_partial_csv(p) is True
    lines = p.read_text().splitlines()
    assert lines == [_HEADER, _ROW1]  # torn row dropped, good row kept


def test_repair_drops_unparseable_date(tmp_path):
    p = _csv(tmp_path, "\n".join([_HEADER, _ROW1, "1979-02-0,0,0,0,0,0"]))
    assert scan_state.repair_partial_csv(p) is True
    assert p.read_text().splitlines() == [_HEADER, _ROW1]


def test_repair_header_only_is_unusable(tmp_path):
    p = _csv(tmp_path, _HEADER + "\n")
    assert scan_state.repair_partial_csv(p) is False


def test_repair_all_rows_torn_is_unusable(tmp_path):
    p = _csv(tmp_path, "\n".join([_HEADER, "garbage", "also,bad"]))
    assert scan_state.repair_partial_csv(p) is False


def test_repair_missing_file_is_unusable(tmp_path):
    assert scan_state.repair_partial_csv(tmp_path / "nope.csv") is False
