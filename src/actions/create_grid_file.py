"""Action: create-grid-file — Emit a HEC-HMS Grid Manager (.grid) file for the catalog.

Uses the older verbose schema (Variant blocks, ``DSS File Name``/``DSS Pathname``,
``Reference Height``, ``Use Lookup Table``) so the file is consumable by HMS 4.x
as well as newer releases. Modern HMS readers still parse Variant blocks for
DSS data sources, so this format is a safe lowest common denominator.

  - 5-space indent on grid sub-keys, 7-space indent inside Variant block
  - LF line endings, UTF-8
  - Date "d MMMM yyyy", Time "HH:mm:ss"
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pyproj import Transformer

log = logging.getLogger(__name__)

INDENT = "     "  # 5 spaces, matches HMS GridManagerWriter.LARGE_INDENT
VARIANT_INDENT = "       "  # 7 spaces, nested inside Variant block
GRID_MANAGER_VERSION = "4.11"
FILEPATH_SEPARATOR = "/"
DEFAULT_VARIANT_NAME = "Variant-1"
DEFAULT_REF_HEIGHT = 10.0
DEFAULT_REF_UNITS = "Meters"

MAX_FAILURE_RATIO = float(os.environ.get("GRID_MAX_FAILURE_RATIO", "0.5"))

# USA Contiguous Albers Equal Area Conic (USGS), US survey feet.
# HEC's SHG reference frame — Storm Center X/Y are expected in this projection.
_ALBERS_CRS_WKT = (
    'PROJCRS["USA_Contiguous_Albers_Equal_Area_Conic_USGS_version",'
    'BASEGEOGCRS["NAD83",DATUM["North American Datum 1983",'
    'ELLIPSOID["GRS 1980",6378137,298.257222101,LENGTHUNIT["metre",1]],'
    'ID["EPSG",6269]],PRIMEM["Greenwich",0,ANGLEUNIT["Degree",0.0174532925199433]]],'
    'CONVERSION["unnamed",METHOD["Albers Equal Area",ID["EPSG",9822]],'
    'PARAMETER["Latitude of false origin",23,ANGLEUNIT["Degree",0.0174532925199433],ID["EPSG",8821]],'
    'PARAMETER["Longitude of false origin",-96,ANGLEUNIT["Degree",0.0174532925199433],ID["EPSG",8822]],'
    'PARAMETER["Latitude of 1st standard parallel",29.5,ANGLEUNIT["Degree",0.0174532925199433],ID["EPSG",8823]],'
    'PARAMETER["Latitude of 2nd standard parallel",45.5,ANGLEUNIT["Degree",0.0174532925199433],ID["EPSG",8824]],'
    'PARAMETER["Easting at false origin",0,LENGTHUNIT["US survey foot",0.304800609601219],ID["EPSG",8826]],'
    'PARAMETER["Northing at false origin",0,LENGTHUNIT["US survey foot",0.304800609601219],ID["EPSG",8827]]],'
    'CS[Cartesian,2],AXIS["(E)",east,ORDER[1],LENGTHUNIT["US survey foot",0.304800609601219,ID["EPSG",9003]]],'
    'AXIS["(N)",north,ORDER[2],LENGTHUNIT["US survey foot",0.304800609601219,ID["EPSG",9003]]]]'
)


def _parse_storm_datetime(item: Any) -> datetime | None:
    """Replicates convert_to_dss._parse_storm_datetime to pair items with DSS files."""
    try:
        return datetime.strptime(item.id, "%Y-%m-%dT%H")
    except ValueError:
        return item.datetime if getattr(item, "datetime", None) else None


def _centroid_lonlat(item: Any) -> tuple[float, float] | None:
    """Extract (lon, lat) from item.geometry (GeoJSON Point set in aorc.py:253)."""
    geom = getattr(item, "geometry", None)
    if not isinstance(geom, dict):
        return None
    if geom.get("type") != "Point":
        return None
    coords = geom.get("coordinates")
    if not (isinstance(coords, (list, tuple)) and len(coords) >= 2):
        return None
    try:
        return float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None


def _earliest_dss_paths(dss_file: Path) -> tuple[str | None, str | None]:
    """Return earliest PRECIPITATION and TEMPERATURE pathnames in a DSS file."""
    from hecdss import HecDss  # runtime dep; not needed for pure-format tests

    precip_path: str | None = None
    temp_path: str | None = None
    earliest_precip: datetime | None = None
    earliest_temp: datetime | None = None

    with HecDss(str(dss_file)) as dss:
        for path_obj in dss.get_catalog():
            path_str = str(path_obj)
            parts = path_str.strip("/").split("/")
            if len(parts) < 6:
                continue
            part_c = parts[2].upper()
            try:
                dt = datetime.strptime(parts[3], "%d%b%Y:%H%M")
            except ValueError:
                continue
            if part_c == "PRECIPITATION":
                if earliest_precip is None or dt < earliest_precip:
                    precip_path, earliest_precip = path_str, dt
            elif part_c == "TEMPERATURE":
                if earliest_temp is None or dt < earliest_temp:
                    temp_path, earliest_temp = path_str, dt

    return precip_path, temp_path


def _render_grid_block(
    *,
    name: str,
    grid_type: str,
    modified_date: str,
    modified_time: str,
    storm_center_xy: tuple[float, float] | None,
    dss_filename: str,
    dss_pathname: str,
) -> list[str]:
    """One grid record in the legacy verbose format (HMS 4.x compatible)."""
    lines = [
        f"Grid: {name}\n",
        f"{INDENT}Grid Type: {grid_type}\n",
        f"{INDENT}Last Modified Date: {modified_date}\n",
        f"{INDENT}Last Modified Time: {modified_time}\n",
        f"{INDENT}Reference Height Units: {DEFAULT_REF_UNITS}\n",
        f"{INDENT}Reference Height: {DEFAULT_REF_HEIGHT}\n",
        f"{INDENT}Data Source Type: External DSS\n",
        f"{INDENT}Variant: {DEFAULT_VARIANT_NAME}\n",
        f"{VARIANT_INDENT}Last Variant Modified Date: {modified_date}\n",
        f"{VARIANT_INDENT}Last Variant Modified Time: {modified_time}\n",
        f"{VARIANT_INDENT}Default Variant: Yes\n",
        f"{VARIANT_INDENT}DSS File Name: {dss_filename}\n",
        f"{VARIANT_INDENT}DSS Pathname: {dss_pathname}\n",
        f"{INDENT}End Variant: {DEFAULT_VARIANT_NAME}\n",
        f"{INDENT}Use Lookup Table: No\n",
    ]
    if storm_center_xy is not None:
        x, y = storm_center_xy
        lines.append(f"{INDENT}Storm Center X: {x}\n")
        lines.append(f"{INDENT}Storm Center Y: {y}\n")
    lines.append("End:\n\n")
    return lines


def build_grid_file(
    entries: Iterable[dict[str, Any]],
    *,
    manager_name: str,
    modified_date: str,
    modified_time: str,
    transformer: Transformer,
) -> str:
    """Compose a full .grid file from ordered entries.

    Each entry: {name, grid_type, dss_filename, dss_pathname, storm_center_lonlat?}.
    Caller controls ordering (typically by storm rank).
    """
    out: list[str] = [
        f"Grid Manager: {manager_name}\n",
        f"{INDENT}Version: {GRID_MANAGER_VERSION}\n",
        f"{INDENT}Filepath Separator: {FILEPATH_SEPARATOR}\n",
        "End:\n\n",
    ]
    for e in entries:
        xy: tuple[float, float] | None = None
        lonlat = e.get("storm_center_lonlat")
        if lonlat is not None:
            x, y = transformer.transform(lonlat[0], lonlat[1])
            xy = (x, y)
        out.extend(
            _render_grid_block(
                name=e["name"],
                grid_type=e["grid_type"],
                modified_date=modified_date,
                modified_time=modified_time,
                storm_center_xy=xy,
                dss_filename=e["dss_filename"],
                dss_pathname=e["dss_pathname"],
            )
        )
    return "".join(out)


def create_grid_file(ctx: dict[str, Any], action: Any) -> None:
    payload = ctx["payload"]
    local_root: Path = ctx["local_root"]
    collection = ctx.get("collection")
    storm_params = ctx.get("storm_params")

    if collection is None or storm_params is None:
        raise RuntimeError(
            "create-grid-file requires ctx['collection'] and ctx['storm_params']; "
            "ensure 'process-storms' ran earlier in the action list"
        )

    attrs = payload.attributes
    catalog_id = attrs["catalog_id"]
    storm_duration = storm_params["storm_duration"]

    output_dir = local_root / catalog_id
    dss_dir = output_dir / "data"
    if not dss_dir.is_dir():
        raise FileNotFoundError(
            f"Data directory not found at {dss_dir}; run 'convert-to-dss' first"
        )

    grid_path = output_dir / "catalog.grid"
    if grid_path.exists():
        log.info("Skipping — %s already exists", grid_path)
        return

    items = list(collection.get_all_items())
    if not items:
        raise RuntimeError("No storm items in collection — nothing to grid")

    transformer = Transformer.from_crs("EPSG:4326", _ALBERS_CRS_WKT, always_xy=True)
    now = datetime.now(timezone.utc)
    modified_date = now.strftime("%d %B %Y").lstrip("0")  # "d MMMM yyyy"
    modified_time = now.strftime("%H:%M:%S")

    entries: list[dict[str, Any]] = []
    failed: list[str] = []

    for idx, item in enumerate(items, start=1):
        storm_start = _parse_storm_datetime(item)
        if storm_start is None:
            log.warning("Skipping item %s: unparseable datetime", item.id)
            failed.append(item.id)
            continue

        date_str = storm_start.strftime("%Y%m%d")
        rank_padded = str(idx).zfill(3)
        dss_filename = f"{date_str}_{storm_duration}hr_st1_r{rank_padded}.dss"
        dss_path = dss_dir / dss_filename

        if not dss_path.exists():
            log.warning("Skipping %s: %s not found", item.id, dss_filename)
            failed.append(item.id)
            continue

        try:
            precip_pn, temp_pn = _earliest_dss_paths(dss_path)
        except Exception as e:
            log.error("Skipping %s: could not read DSS catalog (%s)", item.id, e)
            failed.append(item.id)
            continue

        if precip_pn is None and temp_pn is None:
            log.warning("Skipping %s: no PRECIPITATION or TEMPERATURE paths", item.id)
            failed.append(item.id)
            continue

        lonlat = _centroid_lonlat(item)
        if lonlat is None:
            log.warning(
                "No centroid for %s — emitting grid without Storm Center", item.id
            )

        grid_base = dss_filename[:-4]  # drop ".dss"
        rel_dss = f"data/{dss_filename}"

        if precip_pn is not None:
            entries.append(
                {
                    "name": grid_base,
                    "grid_type": "Precipitation",
                    "dss_filename": rel_dss,
                    "dss_pathname": precip_pn,
                    "storm_center_lonlat": lonlat,
                }
            )
        if temp_pn is not None:
            entries.append(
                {
                    "name": grid_base,
                    "grid_type": "Temperature",
                    "dss_filename": rel_dss,
                    "dss_pathname": temp_pn,
                    "storm_center_lonlat": lonlat,
                }
            )

    total = len(items)
    n_failed = len(failed)
    if n_failed == total:
        raise RuntimeError(
            f"All {total} storms failed grid entry construction: {failed}"
        )
    if total > 0 and n_failed / total > MAX_FAILURE_RATIO:
        raise RuntimeError(
            f"Grid entry failure rate {n_failed}/{total} "
            f"({n_failed / total:.0%}) exceeds threshold ({MAX_FAILURE_RATIO:.0%}): {failed}"
        )

    text = build_grid_file(
        entries,
        manager_name=catalog_id,
        modified_date=modified_date,
        modified_time=modified_time,
        transformer=transformer,
    )
    grid_path.write_text(text, encoding="utf-8", newline="\n")
    log.info(
        "Wrote %s (%d grid records, %d storms)",
        grid_path,
        len(entries),
        total - n_failed,
    )
