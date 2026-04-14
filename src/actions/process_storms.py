"""Action: process-storms — Create STAC catalog and storm collection from NOAA AORC data."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from stormhub.met.storm_catalog import StormCatalog, new_catalog, new_collection

from worker_sizing import resolve_num_workers

log = logging.getLogger(__name__)


def _try_reload_collection(
    catalog_dir: str, catalog_id: str, storm_duration: int
) -> Any | None:
    """Attempt to reload a previously saved catalog + collection from disk."""
    catalog_file = os.path.join(catalog_dir, catalog_id, "catalog.json")
    if not os.path.exists(catalog_file):
        return None

    try:
        catalog = StormCatalog.from_file(catalog_file)
        collection_id = catalog.spm.storm_collection_id(storm_duration)
        collection = catalog.get_child(collection_id)
        if collection is None:
            return None
        # Verify it has items
        items = list(collection.get_all_items())
        if not items:
            return None
        log.info(
            "Reloaded existing collection %s with %d items from disk",
            collection_id,
            len(items),
        )
        return collection
    except Exception as e:
        log.warning("Could not reload collection from disk, will re-create: %s", e)
        return None


def process_storms(ctx: dict[str, Any], action: Any) -> None:
    payload = ctx["payload"]
    local_root: Path = ctx["local_root"]
    config_path: Path = ctx.get("config_path", local_root / "config.json")

    attrs = payload.attributes
    catalog_id = attrs["catalog_id"]

    end_date = attrs.get("end_date", "")
    if not end_date:
        end_date = attrs["start_date"]
        log.info(
            "No end_date specified — defaulting to start_date (%s) for single-day scan",
            end_date,
        )

    storm_params = {
        "start_date": attrs["start_date"],
        "end_date": end_date,
        "storm_duration": int(attrs.get("storm_duration", "72")),
        "min_precip_threshold": float(attrs.get("min_precip_threshold", "0.0")),
        "top_n_events": int(attrs.get("top_n_events", "10")),
        "check_every_n_hours": int(attrs.get("check_every_n_hours", "24")),
        "num_workers": resolve_num_workers(attrs),
        "specific_dates": json.loads(attrs["specific_dates"])
        if attrs.get("specific_dates")
        else [],
    }

    # Try to resume from a previous run's saved catalog/collection
    collection = _try_reload_collection(
        str(local_root), catalog_id, storm_params["storm_duration"]
    )

    if collection is None:
        catalog = new_catalog(
            catalog_id,
            str(config_path),
            local_directory=str(local_root),
            catalog_description=attrs["catalog_description"],
        )

        try:
            collection = new_collection(catalog, **storm_params)
        except BrokenProcessPool as e:
            raise RuntimeError(
                f"Storm processing pool died with num_workers="
                f"{storm_params['num_workers']} (likely OOM). Lower via "
                "'num_workers' payload attribute or CC_NUM_WORKERS env."
            ) from e
        if collection is None:
            raise RuntimeError("no storms found matching criteria")

    log.info("Catalog and collection ready")

    # Store collection in context for downstream actions
    ctx["collection"] = collection
    ctx["storm_params"] = storm_params
