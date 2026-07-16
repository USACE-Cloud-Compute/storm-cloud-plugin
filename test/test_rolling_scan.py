"""Parity tests for rolling_scan — the streaming window-sum core.

The whole point of the rolling-window scan is that ``snapshots[b] - snapshots[a]``
equals the naive per-window re-sum. These tests pin that equivalence (the
"bit-identical" claim) on synthetic data and across chunk boundaries.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from actions import rolling_scan  # noqa: E402


def _provider(cube):
    return lambda a, b: cube[a:b]


def test_snapshots_match_naive_window_sums():
    rng = np.random.default_rng(0)
    T, Y, X = 200, 4, 5
    cube = rng.random((T, Y, X))
    # windows at various (a, b), all snapshotted
    toi = sorted({0, 1, 24, 72, 73, 96, 168, 199})
    snaps, _ = rolling_scan._rolling_snapshots(_provider(cube), T, (Y, X), toi, 30)
    for a in toi:
        for b in toi:
            if a < b:
                assert np.allclose(snaps[b] - snaps[a], cube[a:b].sum(axis=0))


def test_parity_independent_of_chunk_size():
    rng = np.random.default_rng(1)
    T, Y, X = 300, 3, 3
    cube = rng.random((T, Y, X))
    toi = sorted({0, 50, 123, 200, 299})
    ref, _ = rolling_scan._rolling_snapshots(_provider(cube), T, (Y, X), toi, 300)
    for chunk in (1, 7, 30, 128):
        got, _ = rolling_scan._rolling_snapshots(_provider(cube), T, (Y, X), toi, chunk)
        for t in toi:
            assert np.allclose(got[t], ref[t]), f"chunk={chunk} t={t}"


def test_nans_treated_as_zero():
    T, Y, X = 10, 2, 2
    cube = np.ones((T, Y, X))
    cube[3, 0, 0] = np.nan
    snaps, _ = rolling_scan._rolling_snapshots(_provider(cube), T, (Y, X), [0, T], 4)
    # cell (0,0) lost one hour to NaN -> 9, others full 10
    assert snaps[T][0, 0] == pytest.approx(9.0)
    assert snaps[T][1, 1] == pytest.approx(10.0)


def test_enabled_default_on_and_optout(monkeypatch):
    monkeypatch.delenv("CC_ROLLING_SCAN", raising=False)
    assert rolling_scan.enabled() is True
    for off in ("0", "false", "no", "off"):
        monkeypatch.setenv("CC_ROLLING_SCAN", off)
        assert rolling_scan.enabled() is False
