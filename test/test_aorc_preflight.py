"""Unit tests for aorc_preflight — fail-fast AORC year check."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from actions import aorc_preflight  # noqa: E402


def test_required_years_basic():
    assert aorc_preflight.required_years("1979-02-01", "1981-06-01") == [1979, 1980, 1981]


def test_required_years_single_day():
    assert aorc_preflight.required_years("2001-05-05", None) == [2001]


def test_required_years_crosses_boundary_with_duration():
    # A 72-hr window starting 2020-12-31 spills into 2021.
    assert aorc_preflight.required_years("2020-12-31", "2020-12-31", 72) == [2020, 2021]


def test_assert_skips_when_no_base_url(monkeypatch):
    monkeypatch.delenv("AORC_S3_BASE_URL", raising=False)
    # No base URL -> not probeable -> must not raise.
    aorc_preflight.assert_years_available("2001-01-01", "2001-12-31", 72)


def test_assert_raises_on_missing_year(monkeypatch):
    monkeypatch.setattr(aorc_preflight, "verify_aorc_cache_years", lambda years: [2025])
    with pytest.raises(RuntimeError, match="2025"):
        aorc_preflight.assert_years_available("2025-01-01", "2025-12-31", 72)
