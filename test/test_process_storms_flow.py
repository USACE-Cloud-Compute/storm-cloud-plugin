"""Integration tests for the process_storms resume decision routing.

stormhub is stubbed so we can assert *which* path runs (reload / resume / fresh)
under pod-death scenarios, without a real AORC scan.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_SRC / "actions"))

# --- stub stormhub.met.storm_catalog before importing process_storms -------

calls = {"new_catalog": 0, "new_collection": 0, "resume_collection": 0}
state = {"reload_items": None, "resume_fails": False}


class _FakeCollection:
    def __init__(self, items):
        self._items = list(items)

    def get_all_items(self):
        return list(self._items)


class _FakeSPM:
    def storm_collection_id(self, duration):
        return f"{duration}hr-events"


class _FakeCatalog:
    def __init__(self, collection=None):
        self.spm = _FakeSPM()
        self._collection = collection

    def get_child(self, _cid):
        return self._collection


def _new_catalog(catalog_id, _config, local_directory=None, catalog_description=None):
    calls["new_catalog"] += 1
    cat_dir = Path(local_directory) / catalog_id
    cat_dir.mkdir(parents=True, exist_ok=True)
    (cat_dir / "catalog.json").write_text("{}", encoding="utf-8")
    return _FakeCatalog()


def _new_collection(_catalog, **_kw):
    calls["new_collection"] += 1
    return _FakeCollection(["item-1"])


def _resume_collection(_catalog_json, **_kw):
    calls["resume_collection"] += 1
    if state["resume_fails"]:
        raise RuntimeError("simulated resume failure")
    return _FakeCollection(["item-1"])


class _FakeStormCatalog:
    @staticmethod
    def from_file(_path):
        items = state["reload_items"]
        return _FakeCatalog(_FakeCollection(items) if items else None)


_stub = types.ModuleType("stormhub.met.storm_catalog")
_stub.StormCatalog = _FakeStormCatalog
_stub.new_catalog = _new_catalog
_stub.new_collection = _new_collection
_stub.resume_collection = _resume_collection
sys.modules.setdefault("stormhub", types.ModuleType("stormhub"))
sys.modules.setdefault("stormhub.met", types.ModuleType("stormhub.met"))
sys.modules["stormhub.met.storm_catalog"] = _stub

import process_storms  # noqa: E402
import scan_state  # noqa: E402

_HEADER = "storm_date,min,mean,max,x,y"
_ROW = "1979-02-01T00,0.0,1.2,9.9,-100.0,40.0"

_ATTRS = {
    "catalog_id": "cat",
    "catalog_description": "desc",
    "output_path": "s3://bucket/out",
    "start_date": "1979-02-01",
    "end_date": "1979-03-01",
    "storm_duration": "72",
    "top_n_events": "10",
    "check_every_n_hours": "24",
    "min_precip_threshold": "0.0",
}


class _Payload:
    def __init__(self, attrs):
        self.attributes = dict(attrs)


@pytest.fixture(autouse=True)
def _reset():
    calls.update(new_catalog=0, new_collection=0, resume_collection=0)
    state.update(reload_items=None, resume_fails=False)


def _run(tmp_path, attrs=None):
    ctx = {
        "payload": _Payload(attrs or _ATTRS),
        "local_root": tmp_path,
        "config_path": tmp_path / "config.json",
    }
    process_storms.process_storms(ctx, action=None)
    return ctx


def _seed_partial_scan(tmp_path, attrs=None):
    """Simulate a pod that died mid-scan: fingerprint + partial CSV, no sentinel."""
    cat_dir = tmp_path / "cat"
    (cat_dir / "72hr-events").mkdir(parents=True)
    (cat_dir / "catalog.json").write_text("{}", encoding="utf-8")
    (cat_dir / "72hr-events" / "storm-stats.csv").write_text(
        _HEADER + "\n" + _ROW + "\n", encoding="utf-8"
    )
    # Fingerprint matching the run we'll launch.
    params = _fingerprint_params(attrs or _ATTRS)
    scan_state.write_fingerprint(cat_dir, params)


def _fingerprint_params(attrs):
    return {
        "start_date": attrs["start_date"],
        "end_date": attrs["end_date"],
        "storm_duration": int(attrs["storm_duration"]),
        "min_precip_threshold": float(attrs["min_precip_threshold"]),
        "top_n_events": int(attrs["top_n_events"]),
        "check_every_n_hours": int(attrs["check_every_n_hours"]),
        "specific_dates": [],
    }


def test_fresh_when_nothing_on_disk(tmp_path):
    ctx = _run(tmp_path)
    assert calls["new_collection"] == 1 and calls["resume_collection"] == 0
    cat_dir = tmp_path / "cat"
    assert scan_state.is_marked_complete(cat_dir)  # sentinel written
    assert (cat_dir / scan_state.PARAMS_FILE).exists()  # fingerprint written
    assert ctx["collection"] is not None


def test_reload_when_complete_and_matching(tmp_path):
    _run(tmp_path)  # complete a run (writes sentinel + fingerprint)
    calls.update(new_catalog=0, new_collection=0, resume_collection=0)
    state["reload_items"] = ["item-1"]  # reload succeeds

    _run(tmp_path)
    assert calls["new_collection"] == 0 and calls["resume_collection"] == 0  # reloaded


def test_param_drift_quarantines_and_rebuilds(tmp_path):
    _run(tmp_path)  # complete with top_n_events=10
    calls.update(new_catalog=0, new_collection=0, resume_collection=0)

    drifted = dict(_ATTRS, top_n_events="5")
    _run(tmp_path, drifted)

    assert (tmp_path / "cat.quarantine-1").exists()  # old state preserved, not deleted
    assert calls["new_collection"] == 1 and calls["resume_collection"] == 0  # fresh
    # fingerprint now reflects the new request
    assert scan_state.params_match(tmp_path / "cat", _fingerprint_params(drifted))


def test_resume_when_partial_scan_present(tmp_path):
    _seed_partial_scan(tmp_path)
    _run(tmp_path)
    assert calls["resume_collection"] == 1 and calls["new_collection"] == 0
    assert scan_state.is_marked_complete(tmp_path / "cat")


def test_resume_failure_falls_back_to_fresh(tmp_path):
    _seed_partial_scan(tmp_path)
    state["resume_fails"] = True

    ctx = _run(tmp_path)
    assert calls["resume_collection"] == 1  # attempted
    assert calls["new_collection"] == 1  # then rebuilt fresh
    assert (tmp_path / "cat.quarantine-1").exists()  # partial quarantined
    assert ctx["collection"] is not None  # job still completes


def test_incomplete_collection_not_reloaded(tmp_path):
    # catalog.json + fingerprint present but NO sentinel and NO partial CSV:
    # a pod that died mid item-creation. Must not reload a truncated collection.
    cat_dir = tmp_path / "cat"
    cat_dir.mkdir()
    (cat_dir / "catalog.json").write_text("{}", encoding="utf-8")
    scan_state.write_fingerprint(cat_dir, _fingerprint_params(_ATTRS))
    state["reload_items"] = ["item-1"]  # even if reload *could* return items

    _run(tmp_path)
    # No sentinel -> reload not trusted; rebuilt fresh instead.
    assert calls["new_collection"] == 1
