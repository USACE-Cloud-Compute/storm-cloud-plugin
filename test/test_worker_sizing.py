"""Unit tests for worker_sizing.resolve_num_workers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import worker_sizing  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("CC_NUM_WORKERS", raising=False)


@pytest.fixture
def no_cgroup(monkeypatch):
    monkeypatch.setattr(worker_sizing, "_cgroup_mem_limit_mb", lambda: None)


def test_payload_attribute_wins(monkeypatch, no_cgroup):
    monkeypatch.setenv("CC_NUM_WORKERS", "7")
    assert worker_sizing.resolve_num_workers({"num_workers": "3"}) == 3


def test_payload_attribute_floors_at_one(no_cgroup):
    assert worker_sizing.resolve_num_workers({"num_workers": "0"}) == 1


def test_env_used_when_no_attribute(monkeypatch, no_cgroup):
    monkeypatch.setenv("CC_NUM_WORKERS", "5")
    assert worker_sizing.resolve_num_workers({}) == 5


def test_empty_attribute_falls_through(no_cgroup):
    assert worker_sizing.resolve_num_workers({"num_workers": ""}) == 1


def test_auto_sizes_from_cgroup(monkeypatch):
    monkeypatch.setattr(worker_sizing, "_cgroup_mem_limit_mb", lambda: 15000)
    assert worker_sizing.resolve_num_workers({}) == 7  # 15000 // 2048


def test_auto_floors_at_one_when_budget_below_per_worker(monkeypatch):
    monkeypatch.setattr(worker_sizing, "_cgroup_mem_limit_mb", lambda: 512)
    assert worker_sizing.resolve_num_workers({}) == 1


def test_fallback_to_one_when_cgroup_unset(no_cgroup):
    assert worker_sizing.resolve_num_workers({}) == 1


def _patch_cgroup_read(monkeypatch, contents):
    class FakePath:
        def __init__(self, *_): pass
        def read_text(self, **_): return contents
    monkeypatch.setattr(worker_sizing, "Path", FakePath)


def test_cgroup_max_means_unlimited(monkeypatch):
    _patch_cgroup_read(monkeypatch, "max\n")
    assert worker_sizing._cgroup_mem_limit_mb() is None


def test_cgroup_bytes_converted(monkeypatch):
    _patch_cgroup_read(monkeypatch, f"{3 * 1024 * 1024 * 1024}\n")
    assert worker_sizing._cgroup_mem_limit_mb() == 3072


def test_cgroup_huge_sentinel_treated_as_unlimited(monkeypatch):
    _patch_cgroup_read(monkeypatch, str(1 << 63))
    assert worker_sizing._cgroup_mem_limit_mb() is None


def test_cgroup_missing_returns_none(monkeypatch):
    class MissingPath:
        def __init__(self, *_): pass
        def read_text(self, **_): raise FileNotFoundError
    monkeypatch.setattr(worker_sizing, "Path", MissingPath)
    assert worker_sizing._cgroup_mem_limit_mb() is None


def test_cgroup_malformed_returns_none(monkeypatch):
    _patch_cgroup_read(monkeypatch, "garbage")
    assert worker_sizing._cgroup_mem_limit_mb() is None
