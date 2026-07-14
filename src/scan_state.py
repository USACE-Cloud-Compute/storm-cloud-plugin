"""Durable, *validated* resume state for the process-storms scan.

process-storms can run for many hours; a pod can die at any point. These helpers
make resume **safe** rather than merely possible. They refuse to trust on-disk
state that does not match the current request or that is corrupt/partial, and
they *quarantine* (never delete) anything they reject, so a run always makes
forward progress and nothing is silently destroyed.

Three independent guards:

* **Param fingerprint** — the scan is only reusable if the parameters that decide
  *which* dates are searched and *how* events are ranked are unchanged. A changed
  request must never resume onto a catalog built for different parameters (that
  would silently produce a wrong result).
* **Completion sentinel** — a catalog is only trusted as "complete" (reload, skip
  the search) once the whole stage finished. A pod that died between "scan done"
  and "catalog saved" left a partial collection; without the sentinel we resume
  instead of shipping a truncated top-N.
* **CSV repair** — a pod killed mid-write can leave a torn/ragged final row in the
  flushed scan CSV. We keep every well-formed row and drop the rest, so resume
  never miscomputes the missing-date set and never crashes on a partial line.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Files written under the catalog dir (local_root/<catalog_id>/) to track state.
PARAMS_FILE = ".scan-params.json"  # fingerprint of the scan request
COMPLETE_FILE = ".scan-complete"  # sentinel: the scan + catalog fully finished

# The parameters that determine which dates are scanned and how events are ranked.
# If any of these differ from a prior run, that run's partial/complete scan is not
# reusable for this request.
_FINGERPRINT_KEYS = (
    "start_date",
    "end_date",
    "storm_duration",
    "min_precip_threshold",
    "top_n_events",
    "check_every_n_hours",
    "specific_dates",
)

# storm_date column format stormhub writes (see storm_search_results_to_csv_line).
_CSV_DATE_FMT = "%Y-%m-%dT%H"


def fingerprint(storm_params: dict) -> dict:
    """The subset of storm_params that must match for on-disk scan state to be reused."""
    fp: dict = {}
    for key in _FINGERPRINT_KEYS:
        value = storm_params.get(key)
        if isinstance(value, list):
            value = sorted(str(v) for v in value)  # order-insensitive
        fp[key] = value
    return fp


def saved_fingerprint(catalog_dir: Path) -> dict | None:
    """Read the fingerprint recorded by a prior run, or None if absent/unreadable."""
    try:
        return json.loads((catalog_dir / PARAMS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_fingerprint(catalog_dir: Path, storm_params: dict) -> None:
    """Record the current request's fingerprint before the expensive scan starts."""
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / PARAMS_FILE).write_text(
        json.dumps(fingerprint(storm_params), sort_keys=True, indent=2),
        encoding="utf-8",
    )


def params_match(catalog_dir: Path, storm_params: dict) -> bool:
    """True iff a prior fingerprint exists and equals the current request's."""
    saved = saved_fingerprint(catalog_dir)
    return saved is not None and saved == fingerprint(storm_params)


def mark_complete(catalog_dir: Path) -> None:
    """Record that process-storms fully finished — the catalog is safe to reload."""
    (catalog_dir / COMPLETE_FILE).write_text("ok\n", encoding="utf-8")


def is_marked_complete(catalog_dir: Path) -> bool:
    return (catalog_dir / COMPLETE_FILE).exists()


def quarantine(path: Path) -> Path | None:
    """Move `path` aside to a sibling `<name>.quarantine-N`. Never deletes.

    Returns the new location, or None if `path` did not exist.
    """
    if not path.exists():
        return None
    for n in range(1, 1000):
        dest = path.with_name(f"{path.name}.quarantine-{n}")
        if not dest.exists():
            shutil.move(str(path), str(dest))
            log.warning("Quarantined stale/corrupt scan state: %s -> %s", path, dest)
            return dest
    raise RuntimeError(f"Too many quarantine directories beside {path}")


def repair_partial_csv(csv_path: Path) -> bool:
    """Validate and, if needed, repair a partial scan CSV in place.

    A pod killed mid-write can leave a torn or ragged final row. Keep every
    well-formed data row (correct column count + parseable storm_date), drop the
    rest, and rewrite atomically. Returns True iff at least one good data row
    remains — i.e. the CSV is usable to resume from.
    """
    try:
        original = csv_path.read_text(encoding="utf-8")
    except OSError:
        return False

    lines = original.splitlines()
    if len(lines) < 2:  # header only, or empty
        return False

    header = lines[0]
    ncol = header.count(",") + 1
    kept = [header]
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) != ncol:
            continue  # torn / ragged row
        try:
            datetime.strptime(parts[0], _CSV_DATE_FMT)
        except ValueError:
            continue  # unparseable date (partial line)
        kept.append(line)

    if len(kept) < 2:
        return False

    repaired = "\n".join(kept) + "\n"
    if repaired != original:
        dropped = (len(lines) - 1) - (len(kept) - 1)
        tmp = csv_path.with_name(csv_path.name + ".repair-tmp")
        tmp.write_text(repaired, encoding="utf-8")
        os.replace(str(tmp), str(csv_path))  # atomic
        log.warning(
            "Repaired partial scan CSV %s (dropped %d torn/blank row(s), kept %d)",
            csv_path,
            dropped,
            len(kept) - 1,
        )
    return True
