"""Unit tests for create_grid_file.build_grid_file."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from actions.create_grid_file import (  # noqa: E402
    _ALBERS_CRS_WKT,
    build_grid_file,
)


@pytest.fixture
def transformer() -> Transformer:
    return Transformer.from_crs("EPSG:4326", _ALBERS_CRS_WKT, always_xy=True)


def _entry(name: str, grid_type: str, lonlat=None) -> dict:
    return {
        "name": name,
        "grid_type": grid_type,
        "dss_filename": f"data/{name}.dss",
        "dss_pathname": f"/SHG4K/TRINITY/{grid_type.upper()}/01JAN2020:0000/01JAN2020:0100/AORC/",
        "storm_center_lonlat": lonlat,
    }


def test_header_and_trailing_blank_line(transformer):
    text = build_grid_file(
        [], manager_name="cat-1", modified_date="1 January 2020",
        modified_time="00:00:00", transformer=transformer,
    )
    assert text.startswith("Grid Manager: cat-1\n")
    assert "     Version: 4.11\n" in text
    assert "     Filepath Separator: /\n" in text
    assert text.endswith("End:\n\n")


def test_variant_block_and_legacy_keys(transformer):
    text = build_grid_file(
        [_entry("storm1", "Precipitation", (-90.0, 31.0))],
        manager_name="cat-1", modified_date="1 January 2020",
        modified_time="12:34:56", transformer=transformer,
    )
    assert "Grid: storm1\n" in text
    assert "     Grid Type: Precipitation\n" in text
    assert "     Reference Height Units: Meters\n" in text
    assert "     Reference Height: 10.0\n" in text
    assert "     Data Source Type: External DSS\n" in text
    assert "     Variant: Variant-1\n" in text
    assert "       Default Variant: Yes\n" in text
    assert "       DSS File Name: data/storm1.dss\n" in text
    assert "       DSS Pathname: /SHG4K/TRINITY/PRECIPITATION/" in text
    assert "     End Variant: Variant-1\n" in text
    assert "     Use Lookup Table: No\n" in text


def test_storm_center_projected_to_albers(transformer):
    text = build_grid_file(
        [_entry("s", "Precipitation", (-96.0, 23.0))],  # Albers false origin
        manager_name="c", modified_date="1 January 2020",
        modified_time="00:00:00", transformer=transformer,
    )
    # False origin → (0, 0) in Albers, regardless of units
    assert "     Storm Center X: 0" in text
    assert "     Storm Center Y: 0" in text


def test_missing_centroid_omits_storm_center(transformer):
    text = build_grid_file(
        [_entry("s", "Precipitation", None)],
        manager_name="c", modified_date="1 January 2020",
        modified_time="00:00:00", transformer=transformer,
    )
    assert "Storm Center X" not in text
    assert "Storm Center Y" not in text


def test_lf_line_endings(transformer):
    text = build_grid_file(
        [_entry("s", "Temperature", (-90.0, 31.0))],
        manager_name="c", modified_date="1 January 2020",
        modified_time="00:00:00", transformer=transformer,
    )
    assert "\r\n" not in text


def test_multiple_entries_each_end_with_end_marker(transformer):
    text = build_grid_file(
        [_entry("a", "Precipitation"), _entry("a", "Temperature")],
        manager_name="c", modified_date="1 January 2020",
        modified_time="00:00:00", transformer=transformer,
    )
    # Header End: + two grid End: markers = 3 total
    assert text.count("\nEnd:\n") + text.startswith("End:\n") == 3
