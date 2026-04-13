"""Action: download-inputs — Download watershed and transposition geometries from S3."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from cc.plugin_manager import DataSourceOpInput

log = logging.getLogger(__name__)

S3_MAX_RETRIES = 3
S3_RETRY_DELAY = 2  # seconds, doubled each retry


def _s3_download_with_retry(pm: Any, op: DataSourceOpInput, local_path: str) -> None:
    """Download a file from S3 with exponential backoff retry."""
    delay = S3_RETRY_DELAY
    for attempt in range(1, S3_MAX_RETRIES + 1):
        try:
            pm.copy_file_to_local(ds=op, localpath=local_path)
            return
        except Exception:
            if attempt == S3_MAX_RETRIES:
                raise
            log.warning(
                "S3 download attempt %d/%d failed, retrying in %ds",
                attempt,
                S3_MAX_RETRIES,
                delay,
            )
            time.sleep(delay)
            delay *= 2


def _validate_geojson(path: str, key: str) -> None:
    """Validate that a downloaded file is parseable GeoJSON with geometry."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Input '{key}' is not valid JSON: {path} — {e}") from e

    geo_type = data.get("type", "")
    if geo_type in ("Feature", "FeatureCollection"):
        return  # valid GeoJSON
    if geo_type in (
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    ):
        return  # bare geometry object — also valid
    raise ValueError(f"Input '{key}' is not valid GeoJSON (type={geo_type!r}): {path}")


def download_inputs(ctx: dict[str, Any], action: Any) -> None:
    pm = ctx["pm"]
    payload = ctx["payload"]
    local_root: Path = ctx["local_root"]

    for source in payload.inputs:
        for key, remote_path in source.paths.items():
            local_path = str(local_root / Path(remote_path).name)
            op = DataSourceOpInput(name=source.name, pathkey=key, datakey=None)
            log.info("Downloading %s -> %s", remote_path, local_path)
            _s3_download_with_retry(pm, op, local_path)
            _validate_geojson(local_path, key)

    # Create config.json for stormhub
    attrs = payload.attributes
    catalog_id = attrs["catalog_id"]
    input_paths = payload.inputs[0].paths
    watershed_file = str(local_root / Path(input_paths["watershed"]).name)
    transposition_file = str(local_root / Path(input_paths["transposition"]).name)

    config = {
        "watershed": {
            "id": f"{catalog_id}-watershed",
            "geometry_file": watershed_file,
            "description": "Watershed for storm catalog",
        },
        "transposition_region": {
            "id": f"{catalog_id}-transposition",
            "geometry_file": transposition_file,
            "description": "Transposition domain for storm catalog",
        },
    }

    config_path = local_root / "config.json"
    config_path.write_text(json.dumps(config, indent=4), encoding="utf-8")
    log.info("Config file created at %s", config_path)

    # Store config path in context for downstream actions
    ctx["config_path"] = config_path
