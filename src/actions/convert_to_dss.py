"""Action: convert-to-dss — Convert storm events from NOAA Zarr to HEC-DSS format."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# If every storm fails, that's an error. Allow up to this fraction to fail.
MAX_FAILURE_RATIO = float(os.environ.get("DSS_MAX_FAILURE_RATIO", "0.5"))
DSS_WORKERS = int(os.environ.get("DSS_WORKERS", "0"))  # 0 = auto (cpu_count)


def _parse_storm_datetime(item: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(item.id, "%Y-%m-%dT%H")
    except ValueError:
        return item.datetime if item.datetime else None


def _convert_single_storm(
    output_path: str,
    watershed_file: str,
    catalog_id: str,
    storm_start_iso: str,
    storm_duration: int,
) -> Optional[str]:
    """Convert one storm to DSS. Returns error message on failure, None on success.

    Runs in a subprocess via ProcessPoolExecutor, so all args must be picklable.
    """
    from stormhub.met.zarr_to_dss import noaa_zarr_to_dss, NOAADataVariable

    storm_start = datetime.fromisoformat(storm_start_iso)
    try:
        noaa_zarr_to_dss(
            output_dss_path=output_path,
            aoi_geometry_gpkg_path=watershed_file,
            aoi_name=catalog_id,
            storm_start=storm_start,
            variable_duration_map={
                NOAADataVariable.APCP: storm_duration,
                NOAADataVariable.TMP: storm_duration,
            },
        )
        return None
    except Exception as e:
        return str(e)


def convert_to_dss(ctx: dict[str, Any], action: Any) -> None:
    payload = ctx["payload"]
    local_root: Path = ctx["local_root"]
    collection = ctx["collection"]
    storm_params = ctx["storm_params"]

    attrs = payload.attributes
    catalog_id = attrs["catalog_id"]
    output_dir = local_root / catalog_id
    dss_dir = output_dir / "data"
    dss_dir.mkdir(parents=True, exist_ok=True)

    watershed_file = str(local_root / Path(payload.inputs[0].paths["watershed"]).name)
    storm_duration = storm_params["storm_duration"]

    items = list(collection.get_all_items())
    if not items:
        raise RuntimeError("No storm events found in collection — nothing to convert")

    log.info("Converting %d storm events to DSS", len(items))

    # Build work items, skipping unparseable datetimes
    work: list[tuple[str, str, str]] = []  # (item_id, output_path, storm_start_iso)
    skipped: list[str] = []
    for idx, item in enumerate(items, 1):
        storm_start = _parse_storm_datetime(item)
        if storm_start is None:
            log.warning("Skipping item %s: could not parse datetime", item.id)
            skipped.append(item.id)
            continue

        date_str = storm_start.strftime("%Y%m%d")
        rank_padded = str(idx).zfill(3)
        dss_filename = f"{date_str}_{storm_duration}hr_st1_r{rank_padded}.dss"
        output_path = str(dss_dir / dss_filename)

        # Idempotency: skip if DSS file already exists
        if Path(output_path).exists():
            log.info(
                "[%d/%d] Skipping %s — %s already exists",
                idx,
                len(items),
                item.id,
                dss_filename,
            )
            continue

        work.append((item.id, output_path, storm_start.isoformat()))

    failed: list[str] = list(skipped)

    if work:
        workers = (
            DSS_WORKERS if DSS_WORKERS > 0 else min(len(work), os.cpu_count() or 1)
        )
        log.info("Running %d conversions with %d workers", len(work), workers)

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _convert_single_storm,
                    out_path,
                    watershed_file,
                    catalog_id,
                    start_iso,
                    storm_duration,
                ): item_id
                for item_id, out_path, start_iso in work
            }
            for future in as_completed(futures):
                item_id = futures[future]
                error = future.result()
                if error:
                    log.error("Failed to convert %s: %s", item_id, error)
                    failed.append(item_id)
                else:
                    log.info("  Converted %s", item_id)

    total = len(items)
    n_failed = len(failed)
    if n_failed > 0:
        log.warning("DSS conversion: %d/%d failed: %s", n_failed, total, failed)

    if n_failed == total:
        raise RuntimeError(f"All {total} DSS conversions failed: {failed}")

    if total > 0 and (n_failed / total) > MAX_FAILURE_RATIO:
        raise RuntimeError(
            f"DSS conversion failure rate {n_failed}/{total} "
            f"({n_failed / total:.0%}) exceeds threshold ({MAX_FAILURE_RATIO:.0%}): {failed}"
        )

    log.info("DSS conversion complete. Output: %s", dss_dir)
