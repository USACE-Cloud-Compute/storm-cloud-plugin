"""Rolling-window AORC scan — O(area × T) instead of O(area × D × num_dates).

The upstream pipeline reads ``storm_duration`` hours of precip per
storm-date and sums them. With ``check_every_n_hours`` < ``storm_duration``
consecutive windows overlap heavily — each hour of data gets read and
summed roughly ``storm_duration / check_every_n_hours`` times.

This module sweeps each year once. For every storm-date we only need
two snapshots of the running cumulative sum (one at the window start,
one just past the window end), so the algorithm is:

1. For each year, compute the set of "times of interest" — for each
   storm-date ``d``, ``i_start = idx_of(d + 1h)`` and ``i_end1 = idx_of(d + D) + 1``.
2. Stream the year's transposition-bbox precip in time-chunks
   (default 720h = 1 month). Maintain a running cumulative sum
   ``(Y, X) float64``. Whenever the stream passes a time-of-interest,
   snapshot the running sum.
3. For each storm-date: ``window_sum = snapshot[i_end1] - snapshot[i_start]``,
   feed into the reused ``Transpose`` object, write CSV row.

Peak memory is bounded by one chunk + the snapshot pool (~3 GB for a
1000×1000 transposition bbox), not by the full-year cube (which would
be tens of GB for large domains).

Bit-equivalent to upstream at valid shifts. ``valid_shifts`` is
computed once from a 2D template that has the rio.clip NaN pattern.
At any valid shift the watershed window only overlaps cells that were
finite in the original data, so treating NaN as 0 in the running sum
cannot perturb any mean we'll actually emit.

Gating: on by default — set ``CC_ROLLING_SCAN=0`` to opt out. Chunk size:
``CC_ROLLING_CHUNK_HOURS`` (default 720).
"""

from __future__ import annotations

import datetime
import gc
import logging
import multiprocessing
import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Callable

import numpy as np

log = logging.getLogger(__name__)

# Spawn, not fork: s3fs's async event-loop thread doesn't survive fork()
# and deadlocks child Event.wait() on first S3 read. Same fix used in
# convert_to_dss and stormhub's own pools.
_SPAWN_CTX = multiprocessing.get_context("spawn")


def enabled() -> bool:
    """Whether the rolling-scan path is active. On by default; set CC_ROLLING_SCAN=0 to opt out."""
    return os.environ.get("CC_ROLLING_SCAN", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


_CHUNK_HOURS = int(os.environ.get("CC_ROLLING_CHUNK_HOURS", "720"))

_original_collect_event_stats: Callable | None = None


def install() -> None:
    """Replace ``stormhub.met.storm_catalog.collect_event_stats``."""
    global _original_collect_event_stats
    from stormhub.met import storm_catalog as sc_mod

    if _original_collect_event_stats is not None:
        return
    _original_collect_event_stats = sc_mod.collect_event_stats
    sc_mod.collect_event_stats = rolling_collect_event_stats
    log.info(
        "Rolling-window AORC scan installed (CC_ROLLING_SCAN=1, chunk=%dh)",
        _CHUNK_HOURS,
    )


def restore() -> None:
    global _original_collect_event_stats
    from stormhub.met import storm_catalog as sc_mod

    if _original_collect_event_stats is None:
        return
    sc_mod.collect_event_stats = _original_collect_event_stats
    _original_collect_event_stats = None


def rolling_collect_event_stats(
    event_dates: list,
    catalog: Any,
    collection_id: str | None = None,
    storm_duration: int = 72,
    num_workers: int | None = None,
    use_threads: bool = False,
    with_tb: bool = False,
    use_parallel_processing: bool = True,
) -> None:
    """Drop-in replacement for ``stormhub.met.storm_catalog.collect_event_stats``.

    Groups storm-dates by year, then processes years in parallel via
    ProcessPoolExecutor (one worker per year, fan-out capped at
    ``num_workers``). Each worker streams its year's transposition-bbox
    precip in 1-month chunks, accumulating a running cumulative sum and
    snapshotting it at the indices each storm-date needs. Memory per
    worker is bounded to ~one chunk + snapshot pool (~3 GB).
    """
    from shapely.geometry import shape

    if not collection_id:
        collection_id = catalog.spm.storm_collection_id(storm_duration)
    collection_dir = catalog.spm.collection_dir(collection_id)
    os.makedirs(collection_dir, exist_ok=True)
    csv_path = os.path.join(collection_dir, "storm-stats.csv")

    # Geometries are picklable; the catalog itself isn't (file refs +
    # pystac links). Workers receive only the primitives they need.
    watershed_geom = shape(catalog.watershed.geometry)
    transposition_geom = shape(catalog.valid_transposition_region.geometry)

    by_year: dict[int, list] = defaultdict(list)
    for d in event_dates:
        by_year[d.year].append(d)
    years_sorted = sorted(by_year.keys())

    total = len(event_dates)
    t_overall = time.monotonic()

    if not years_sorted:
        # No dates to process — emit the header-only CSV upstream expects.
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("storm_date,min,mean,max,x,y\n")
        log.info("[rolling-scan] DONE: no event dates supplied")
        return

    workers = max(1, int(num_workers or 1))
    workers = min(workers, len(years_sorted))
    workers = _cap_workers_by_memory(
        workers, by_year, transposition_geom.bounds, _CHUNK_HOURS
    )
    log.info(
        "[rolling-scan] dispatching %d years across %d worker(s)",
        len(years_sorted),
        workers,
    )

    # Per-year results: year -> (lines, completed, skipped). Workers may
    # complete out of order; we sort by year when writing the final CSV.
    results: dict[int, tuple[list[str], int, int]] = {}
    failed_years: list[tuple[int, str]] = []

    def _submit_args(year: int):
        return (
            year,
            sorted(by_year[year]),
            storm_duration,
            watershed_geom,
            transposition_geom,
            _CHUNK_HOURS,
        )

    if workers == 1:
        # Sequential path — keeps a single process for debugging and
        # matches the legacy in-process execution.
        for year in years_sorted:
            try:
                y, lines, c, s = _process_one_year(*_submit_args(year))
                results[y] = (lines, c, s)
                _log_year_done(y, c, s, len(results), len(years_sorted), t_overall)
            except Exception as e:
                log.error("[rolling-scan] year=%d FAILED: %s", year, e)
                failed_years.append((year, str(e)))
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=_SPAWN_CTX) as ex:
            futures = {
                ex.submit(_process_one_year, *_submit_args(y)): y for y in years_sorted
            }
            for fut in as_completed(futures):
                year = futures[fut]
                try:
                    y, lines, c, s = fut.result()
                    results[y] = (lines, c, s)
                    _log_year_done(y, c, s, len(results), len(years_sorted), t_overall)
                except Exception as e:
                    log.error("[rolling-scan] year=%d FAILED: %s", year, e)
                    failed_years.append((year, str(e)))

    # Write CSV once at end, in year-sorted order. Header first; idempotency
    # is "all-or-nothing" — interrupted runs get partial results and the
    # operator wipes the dir to re-launch. (Resume across crashes would
    # require per-year temp files; not worth the complexity vs ~10 min
    # full-rerun cost.)
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("storm_date,min,mean,max,x,y\n")
        for year in sorted(results):
            f.writelines(results[year][0])

    completed = sum(r[1] for r in results.values())
    skipped = sum(r[2] for r in results.values())
    log.info(
        "[rolling-scan] DONE: %d/%d processed (skipped=%d, failed_years=%d) in %.1fs",
        completed,
        total,
        skipped,
        len(failed_years),
        time.monotonic() - t_overall,
    )
    if failed_years:
        # Surface per-year failures but don't raise — the run continues with
        # whatever years succeeded, matching the per-storm-date soft-error
        # behaviour of the upstream parallel_threads path.
        for y, msg in failed_years:
            log.error("[rolling-scan] year=%d unrecoverable: %s", y, msg)


# AORC native resolution: 1 km grid ≈ 0.0083° at mid-latitudes. Slight
# over-estimate at high latitudes (where cells shrink in longitude) — that
# direction is the safe one for a worker-sizing cap.
_AORC_DEG_PER_CELL = 0.0083

# Reserve headroom in the cgroup budget for the main process, dask threads,
# numpy temporaries, and allocator fragmentation. 10% on a 30 GiB cgroup is
# ~3 GiB which empirically covers what we've observed in production runs.
_MAIN_PROCESS_OVERHEAD = 0.10

# Per-worker peak floor: don't size below this even if the bbox is tiny, so
# we don't blow up on small-bbox catalogs with a huge year-of-dates scan.
_MIN_PER_WORKER_MB = 512

# Multiplier on the raw byte cost: covers numpy temporaries, allocator
# slack, dask sub-chunk reads. Calibrated empirically — the 2026-05-27
# OOM crashes (both 6-worker and 3-worker) confirmed that the worst peak
# isn't (snapshot + chunk_cum), it's the chunk-load transient where four
# arrays coexist for one numpy expression. See _estimate_per_worker_mb.
_PER_WORKER_OVERHEAD = 1.2

# Python + stormhub + dask + s3fs imports baseline per spawn worker.
_PYTHON_BASELINE_MB = 500


def _aorc_cells_from_bounds(bounds: tuple[float, float, float, float]) -> int:
    """Estimate AORC cell count from a (minx, miny, maxx, maxy) lon/lat bbox."""
    n_lon = max(1.0, (bounds[2] - bounds[0]) / _AORC_DEG_PER_CELL)
    n_lat = max(1.0, (bounds[3] - bounds[1]) / _AORC_DEG_PER_CELL)
    return int(n_lon * n_lat)


def _cgroup_mem_mb() -> int | None:
    """Project an effective memory budget in MiB.

    Tries cgroup v2 ``memory.max`` first; falls back to /proc/meminfo when the
    cgroup is unbounded (the common case for ``docker run`` without
    ``--memory``). The kernel will OOM-kill on host-RAM exhaustion regardless
    of whether docker set a cgroup limit, so the fallback is the right safety
    bound — not "no limit, run as many workers as you want".

    Returns None only if neither source is readable.
    """
    cgroup_mb: int | None = None
    try:
        raw = open("/sys/fs/cgroup/memory.max", encoding="utf-8").read().strip()
        if raw != "max":
            b = int(raw)
            if 0 < b < (1 << 62):  # kernel sentinels for "no limit" are huge
                cgroup_mb = b // (1024 * 1024)
    except (OSError, FileNotFoundError, ValueError):
        pass

    host_mb: int | None = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    # "MemTotal:    31234567 kB"
                    host_mb = int(line.split()[1]) // 1024
                    break
    except (OSError, ValueError, IndexError):
        pass

    if cgroup_mb is not None and host_mb is not None:
        return min(cgroup_mb, host_mb)
    return cgroup_mb if cgroup_mb is not None else host_mb


def _estimate_per_worker_mb(
    max_snapshots: int, bbox_cells: int, chunk_hours: int
) -> int:
    """Project a single rolling worker's peak RSS in MiB.

    Two RSS peaks are reached during a year's work; we size for the WORST.
    The late-year chunk-load transient dominates:

    1. ``snapshot pool``     — float64, grows to ``max_snapshots × bbox × 8``
    2. ``chunk transient``   — during ``chunk_filled = np.where(...).astype(float64)``
       four allocations are alive briefly:
           raw f32 chunk        : 4 × chunk_hours × bbox
         + np.where()  f32      : 4 × chunk_hours × bbox
         + chunk_filled f64     : 8 × chunk_hours × bbox
         + chunk_cum    f64     : 8 × chunk_hours × bbox  (allocated next)
       = ``24 × chunk_hours × bbox`` bytes before the ``del chunk, chunk_filled``.

    The first version of this estimator only counted (snapshot + chunk_cum +
    raw_chunk) and missed the transient — predicted ~6.6 GiB for indian-creek
    when the real peak was ~9.5 GiB, sized the pool to 3 workers, and the
    rerun OOM-crashed at chunk load.
    """
    snapshot_bytes = max_snapshots * bbox_cells * 8
    chunk_transient_bytes = 24 * chunk_hours * bbox_cells
    raw_mb = (snapshot_bytes + chunk_transient_bytes) / (1024 * 1024)
    mb = int(raw_mb * _PER_WORKER_OVERHEAD) + _PYTHON_BASELINE_MB
    return max(_MIN_PER_WORKER_MB, mb)


def _cap_workers_by_memory(
    requested: int,
    by_year: dict[int, list],
    bounds: tuple[float, float, float, float],
    chunk_hours: int,
) -> int:
    """Return ``requested`` capped so the projected worker pool fits the cgroup.

    workers.py auto-sizes by a flat ``PER_WORKER_MB_THREADS=4096`` budget
    that's right for ~300×400 cell bboxes (Whitehorse) but underprovisions
    for ~400×800+ bboxes (indian-creek, kanawha). Without this cap, the
    pool can request ~34 GiB on a 30 GiB cgroup and the kernel OOM-kills
    one worker, triggering BrokenProcessPool across the whole scan.

    No cap is applied if the cgroup limit can't be read (unbounded host).
    """
    cg_mb = _cgroup_mem_mb()
    if cg_mb is None:
        log.info(
            "[rolling-scan] cgroup memory.max unset; trusting num_workers=%d",
            requested,
        )
        return requested

    cells = _aorc_cells_from_bounds(bounds)
    max_snaps = max((len(d) for d in by_year.values()), default=1)
    per_worker = _estimate_per_worker_mb(max_snaps, cells, chunk_hours)
    safe_budget = int(cg_mb * (1.0 - _MAIN_PROCESS_OVERHEAD))
    safe_workers = max(1, safe_budget // per_worker)
    capped = min(requested, safe_workers)

    if capped < requested:
        log.warning(
            "[rolling-scan] capping num_workers=%d -> %d "
            "(per-worker peak ~%d MiB × %d > %d MiB budget; "
            "bbox≈%d cells, max snapshots/year=%d, chunk=%dh). "
            "Override via CC_NUM_WORKERS once you've increased --memory.",
            requested,
            capped,
            per_worker,
            requested,
            safe_budget,
            cells,
            max_snaps,
            chunk_hours,
        )
    else:
        log.info(
            "[rolling-scan] num_workers=%d fits memory budget "
            "(per-worker peak ~%d MiB, %d MiB budget, safe max=%d)",
            requested,
            per_worker,
            safe_budget,
            safe_workers,
        )
    return capped


def _log_year_done(year, completed, skipped, done_count, total_years, t_overall):
    elapsed = time.monotonic() - t_overall
    log.info(
        "[rolling-scan] year=%d done (completed=%d, skipped=%d) — %d/%d years in %.1fs",
        year,
        completed,
        skipped,
        done_count,
        total_years,
        elapsed,
    )


def _open_aorc_resilient(years_needed, bounds, transposition_geom):
    """Open AORC zarr for ``years_needed``, falling back when years are missing.

    Returns ``(precip_da, years_actually_opened)``. If the trailing year
    (``year+1``) is missing from the private cache (e.g. partial-year
    upload still in progress), retries with just ``[year]`` and cross-year
    storms will be auto-skipped by ``time_to_idx`` lookups (their end
    index falls outside the dataset).

    Raises if even the primary year is unreadable.
    """
    from stormhub.met.consts import AORC_PRECIP_VARIABLE, NOAA_AORC_S3_BASE_URL
    from stormhub.met.zarr_to_dss import open_aorc_zarr

    remaining = list(years_needed)
    while remaining:
        paths = tuple(f"{NOAA_AORC_S3_BASE_URL}/{y}.zarr" for y in remaining)
        try:
            ds = open_aorc_zarr(paths)
            precip_da = ds[AORC_PRECIP_VARIABLE].sel(
                longitude=slice(bounds[0], bounds[2]),
                latitude=slice(bounds[1], bounds[3]),
            )
            precip_da = precip_da.rio.clip(
                [transposition_geom], drop=True, all_touched=True
            )
            # Force a metadata read so missing keys raise here, not later
            # mid-stream when the failure is harder to recover from.
            _ = precip_da.sizes
            return precip_da, remaining
        except (KeyError, FileNotFoundError) as e:
            if len(remaining) == 1:
                raise  # primary year missing — caller decides what to do
            dropped = remaining.pop()
            logging.getLogger(__name__).warning(
                "[rolling-scan] open failed for %s (%s); retrying without year=%d",
                paths,
                e,
                dropped,
            )


def _rolling_snapshots(
    chunk_provider: Callable[[int, int], np.ndarray],
    T: int,
    shape_yx: tuple[int, int],
    toi_sorted: list[int],
    chunk_hours: int,
) -> tuple[dict[int, np.ndarray], int]:
    """Streaming cumulative-sum snapshots — the numerical core of the scan.

    Streams the precip cube in ``chunk_hours`` slabs via ``chunk_provider``
    (``(start, stop) -> ndarray[stop-start, Y, X]``), maintains a running
    cumulative sum, and snapshots it at each time-of-interest in
    ``toi_sorted`` (which must start with 0). ``snapshots[t]`` is the sum of
    precip hours ``0..t-1``; a window sum is then ``snapshots[b] -
    snapshots[a]`` for ``a < b``. This is exactly stormhub's per-date window
    sum, computed once per year instead of re-summing each window — the
    "bit-identical" claim parity-tested in test_rolling_scan.py.

    Returns ``(snapshots, bytes_streamed)``. NaNs are treated as 0 (matching
    the per-date path's masking) and accumulation is in float64.
    """
    Y, X = shape_yx
    running = np.zeros((Y, X), dtype=np.float64)
    snapshots: dict[int, np.ndarray] = {0: running.copy()}
    bytes_streamed = 0
    next_toi_idx = 1  # toi_sorted[0] == 0, already snapshotted

    for chunk_start in range(0, T, chunk_hours):
        chunk_end = min(chunk_start + chunk_hours, T)
        chunk = chunk_provider(chunk_start, chunk_end)
        bytes_streamed += chunk.nbytes

        chunk_filled = np.where(np.isfinite(chunk), chunk, 0.0).astype(np.float64)
        chunk_cum = np.cumsum(chunk_filled, axis=0)
        del chunk, chunk_filled

        # Snapshot any time-of-interest that falls in (chunk_start, chunk_end].
        # rolling[t] = running (sum before chunk) + chunk_cum[t - chunk_start - 1].
        while next_toi_idx < len(toi_sorted):
            t_idx = toi_sorted[next_toi_idx]
            if t_idx <= chunk_start:
                next_toi_idx += 1
                continue
            if t_idx > chunk_end:
                break
            local = t_idx - chunk_start - 1
            snapshots[t_idx] = running + chunk_cum[local]
            next_toi_idx += 1

        running = running + chunk_cum[-1]
        del chunk_cum

    return snapshots, bytes_streamed


def _process_one_year(
    year: int,
    dates_in_year: list,
    storm_duration: int,
    watershed_geom: Any,
    transposition_geom: Any,
    chunk_hours: int,
) -> tuple[int, list[str], int, int]:
    """Process one year's storm-dates. Returns ``(year, csv_lines, completed, skipped)``.

    Runs in a spawn-based subprocess via ProcessPoolExecutor — must not
    reference unpicklable module-level state.
    """
    # Worker-local logging — main process uses the root logger, but each
    # spawn worker starts with no handlers configured.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    wlog = logging.getLogger(f"rolling.year{year}")

    from stormhub.met.transpose import Transpose

    bounds = transposition_geom.bounds
    t_year = time.monotonic()

    max_end = max(d + datetime.timedelta(hours=storm_duration) for d in dates_in_year)
    years_needed = list(range(year, max_end.year + 1))
    wlog.info(
        "[rolling-scan] year=%s requesting years=%s for %d dates",
        year,
        years_needed,
        len(dates_in_year),
    )

    try:
        precip_da, years_opened = _open_aorc_resilient(
            years_needed, bounds, transposition_geom
        )
    except Exception as e:
        wlog.error("[rolling-scan] year=%d cannot open AORC: %s", year, e)
        # Skip entire year. Caller treats the empty result as soft-failure.
        return year, [], 0, len(dates_in_year)

    if years_opened != years_needed:
        wlog.warning(
            "[rolling-scan] year=%d opened only %s (cross-year storms will skip)",
            year,
            years_opened,
        )

    T = precip_da.sizes["time"]
    Y = precip_da.sizes["latitude"]
    X = precip_da.sizes["longitude"]
    wlog.info(
        "[rolling-scan] year=%d clipped time=%d lat=%d lon=%d (~%.1f GB cube avoided)",
        year,
        T,
        Y,
        X,
        T * Y * X * 4 / 1e9,
    )

    # Map zarr-time to integer index using a small probe.
    times_np = precip_da.time.values
    time_to_idx: dict[datetime.datetime, int] = {}
    for i, t in enumerate(times_np):
        ts = (t - np.datetime64("1970-01-01T00:00:00")) / np.timedelta64(1, "s")
        time_to_idx[datetime.datetime.utcfromtimestamp(float(ts))] = i

    # Build the set of rolling-indices each date needs.
    date_to_io = {}
    toi: set[int] = {
        0
    }  # snapshot[0] = zeros (used as lower edge for early-year windows)
    for d in dates_in_year:
        start_t = d + datetime.timedelta(hours=1)
        end_t = d + datetime.timedelta(hours=storm_duration)
        i0 = time_to_idx.get(start_t)
        i1 = time_to_idx.get(end_t)
        if i0 is None or i1 is None:
            continue
        date_to_io[d] = (i0, i1 + 1)
        toi.add(i0)
        toi.add(i1 + 1)
    toi_sorted = sorted(toi)
    wlog.info(
        "[rolling-scan] year=%d %d snapshots over T=%d",
        year,
        len(toi_sorted),
        T,
    )

    # Stream the precip cube in chunk_hours slabs, maintain a running
    # cumulative sum, snapshot at each time-of-interest. The numerical core
    # is extracted into _rolling_snapshots (parity-tested); here we just feed
    # it zarr slabs via a chunk provider.
    t_stream = time.monotonic()

    def _provider(cs: int, ce: int) -> np.ndarray:
        return precip_da.isel(time=slice(cs, ce)).compute().values

    snapshots, bytes_streamed = _rolling_snapshots(
        _provider, T, (Y, X), toi_sorted, chunk_hours
    )

    wlog.info(
        "[rolling-scan] year=%d stream done %.1fs (%.1f GB read, %d snapshots)",
        year,
        time.monotonic() - t_stream,
        bytes_streamed / 1e9,
        len(snapshots),
    )

    # Build Transpose from a 2D template with the rio.clip NaN pattern.
    template = precip_da.isel(time=0).compute()
    transpose_obj = Transpose(template, watershed_geom, "longitude", "latitude")
    _ = transpose_obj.valid_shifts

    lines: list[str] = []
    skipped = 0
    completed = 0
    t_dates = time.monotonic()
    for storm_start in dates_in_year:
        io = date_to_io.get(storm_start)
        if io is None:
            skipped += 1
            continue
        i0, i1p1 = io
        window_sum = snapshots[i1p1] - snapshots[i0]

        transpose_obj._np_data_array = window_sum  # float64
        poly, _aff, stats = transpose_obj.max_transpose(_create_stats)
        centroid = poly.centroid
        lines.append(
            f"{storm_start.strftime('%Y-%m-%dT%H')},"
            f"{stats['min']},{stats['mean']},{stats['max']},"
            f"{centroid.x},{centroid.y}\n"
        )
        completed += 1

    wlog.info(
        "[rolling-scan] year=%d per-date pass: %.1fs (%d dates, %.3fs/date) — year total %.1fs",
        year,
        time.monotonic() - t_dates,
        len(date_to_io),
        (time.monotonic() - t_dates) / max(1, len(date_to_io)),
        time.monotonic() - t_year,
    )

    # Log this worker's peak RSS so the per-worker estimator's predictions are
    # auditable against reality. Linux ru_maxrss is reported in KiB; macOS in
    # bytes. We assume Linux (the container is) but coerce just in case.
    try:
        import resource

        peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_mb = peak_kb // 1024
        wlog.info("[rolling-scan] year=%d worker peak RSS: %d MiB", year, peak_mb)
    except (ImportError, OSError):
        pass  # platform without resource module — fine, not load-bearing

    del snapshots, transpose_obj
    gc.collect()
    return year, lines, completed, skipped


def _create_stats(array: np.ndarray) -> dict:
    """Match ``stormhub.met.aorc.aorc.AORCItem._create_stats``."""
    from stormhub.met.consts import MM_TO_INCH_CONVERSION_FACTOR

    return {
        "min": round(float(np.nanmin(array)) * MM_TO_INCH_CONVERSION_FACTOR, 2),
        "mean": round(float(np.nanmean(array)) * MM_TO_INCH_CONVERSION_FACTOR, 2),
        "max": round(float(np.nanmax(array)) * MM_TO_INCH_CONVERSION_FACTOR, 2),
        "units": "inches",
    }
