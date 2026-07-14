"""Action: process-storms — Create STAC catalog and storm collection from NOAA AORC data."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from stormhub.met.storm_catalog import (
    StormCatalog,
    new_catalog,
    new_collection,
    resume_collection,
)

from worker_sizing import resolve_num_workers
import scan_state

log = logging.getLogger(__name__)


def _can_resume_scan(
    catalog_dir: Path, storm_duration: int, storm_params: dict
) -> bool:
    """True iff a trustworthy partial scan exists to resume from.

    Requires all of: matching param fingerprint (guards against resuming onto a
    catalog built for a different request), a saved catalog.json, and a
    ``storm-stats.csv`` that holds at least one well-formed row after repair.
    ``specific_dates`` runs can't be resumed by missing-date diffing, so they
    always rebuild.
    """
    if storm_params["specific_dates"]:
        return False
    if not scan_state.params_match(catalog_dir, storm_params):
        return False
    catalog_json = catalog_dir / "catalog.json"
    stats_csv = catalog_dir / f"{storm_duration}hr-events" / "storm-stats.csv"
    if not (catalog_json.exists() and stats_csv.exists()):
        return False
    return scan_state.repair_partial_csv(stats_csv)


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


def _oom_runtime_error(storm_params: dict) -> RuntimeError:
    return RuntimeError(
        f"Storm processing pool died with num_workers="
        f"{storm_params['num_workers']} (likely OOM). Lower via "
        "'num_workers' payload attribute or CC_NUM_WORKERS env."
    )


def _build_collection(
    *,
    resume: bool,
    catalog_dir: Path,
    catalog_json: Path,
    config_path: Path,
    catalog_id: str,
    local_root: Path,
    attrs: Any,
    storm_params: dict,
) -> Any:
    """Build the storm collection, resuming the partial scan when safe.

    A resume that fails for any *non-OOM* reason is not fatal: the partial state
    is quarantined and the scan is rebuilt from scratch exactly once, so a bug on
    the resume path can never strand an otherwise-runnable job. OOM
    (``BrokenProcessPool``) is re-raised with actionable guidance — retrying fresh
    would just OOM again.
    """

    def _fresh() -> Any:
        catalog = new_catalog(
            catalog_id,
            str(config_path),
            local_directory=str(local_root),
            catalog_description=attrs["catalog_description"],
        )
        # Record the fingerprint before the multi-hour scan so a mid-scan death is
        # resumable on the next attempt.
        scan_state.write_fingerprint(catalog_dir, storm_params)
        return new_collection(catalog, **storm_params)

    try:
        if resume:
            log.info("Resuming scan — searching only the missing dates")
            resume_params = {
                k: v for k, v in storm_params.items() if k != "specific_dates"
            }
            collection = resume_collection(str(catalog_json), **resume_params)
        else:
            log.info("Running a fresh storm search")
            collection = _fresh()
    except BrokenProcessPool as e:
        raise _oom_runtime_error(storm_params) from e
    except Exception as e:
        if not resume:
            raise
        log.warning(
            "Resume failed (%s) — quarantining partial state and rebuilding fresh", e
        )
        scan_state.quarantine(catalog_dir)
        try:
            collection = _fresh()
        except BrokenProcessPool as e2:
            raise _oom_runtime_error(storm_params) from e2

    if collection is None:
        raise RuntimeError("no storms found matching criteria")
    return collection


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

    # Resume ladder. Every rung relies on local_root being durable across pod
    # restarts (see the CC_LOCAL_ROOT mount in plugin.py); on ephemeral storage
    # only the fresh path is ever taken. Each rung is guarded so resume is
    # *trustworthy*, not merely possible — see scan_state for the guards.
    storm_duration = storm_params["storm_duration"]
    catalog_dir = Path(local_root) / catalog_id
    catalog_json = catalog_dir / "catalog.json"

    # Guard 1 (param drift): state left by a run with different parameters must
    # never be reused — resuming onto it would silently build a wrong catalog.
    # Quarantine it (keep for debugging) and start clean.
    saved = scan_state.saved_fingerprint(catalog_dir)
    if saved is not None and saved != scan_state.fingerprint(storm_params):
        log.warning("Scan parameters changed since the last run — not reusing stale state")
        scan_state.quarantine(catalog_dir)

    # Rung 1 (reload): trust a complete catalog only when the completion sentinel
    # is present AND the fingerprint matches. A bare catalog.json may be a
    # half-built collection from a pod that died during item creation.
    collection = None
    if scan_state.params_match(catalog_dir, storm_params) and scan_state.is_marked_complete(
        catalog_dir
    ):
        collection = _try_reload_collection(str(local_root), catalog_id, storm_duration)
        if collection is None:
            log.warning("Completion marker present but catalog would not reload — rebuilding")

    # Rungs 2 & 3 (resume the partial scan, else fresh search).
    if collection is None:
        resume = _can_resume_scan(catalog_dir, storm_duration, storm_params)
        collection = _build_collection(
            resume=resume,
            catalog_dir=catalog_dir,
            catalog_json=catalog_json,
            config_path=config_path,
            catalog_id=catalog_id,
            local_root=local_root,
            attrs=attrs,
            storm_params=storm_params,
        )
        scan_state.mark_complete(catalog_dir)

    log.info("Catalog and collection ready")

    # Store collection in context for downstream actions
    ctx["collection"] = collection
    ctx["storm_params"] = storm_params
