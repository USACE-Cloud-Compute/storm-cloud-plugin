"""Pre-flight: verify every year in the payload's date range is mirrored.

Before kicking off process-storms (which can take 10+ minutes), HEAD each
year's ``.zmetadata`` in the AORC cache. If any year is missing, raise
with a clear "mirror these years first" message — failing in seconds
instead of mid-scan with a cryptic xarray/zarr ``KeyError: '.zmetadata'``.

This is the regression guard for the 2026-05-27 incident where the
2025.zarr key was never mirrored, the catalog runs got 30+ minutes into
process-storms, the cumsum path opened (2024, 2025) for cross-year
storms, and the whole run crashed when zarr couldn't find ``.zmetadata``.

No-op when ``AORC_S3_BASE_URL`` isn't set (local dev). Logs warnings but
doesn't raise when ``AORC_S3_KEY`` / ``AORC_S3_SECRET`` are absent — we
have no way to probe a private bucket without them, and the actual scan
will fail later with a more specific error.
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Iterable
from urllib.parse import urlparse

log = logging.getLogger(__name__)


def required_years(
    start_date: str, end_date: str | None, storm_duration_hours: int = 0
) -> list[int]:
    """Years whose AORC zarrs the scan needs.

    ``start.year`` through ``end.year`` inclusive; one extra year tacked on
    when ``end_date`` + ``storm_duration`` crosses a year boundary (the
    cumsum path opens ``(year, year+1)`` for late-year storm windows).
    """
    start = datetime.date.fromisoformat(start_date)
    end = datetime.date.fromisoformat(end_date) if end_date else start
    last = end + datetime.timedelta(hours=storm_duration_hours)
    return list(range(start.year, last.year + 1))


def verify_aorc_cache_years(
    years: Iterable[int], aorc_base_url: str | None = None
) -> list[int]:
    """Return the subset of ``years`` whose ``.zmetadata`` is missing in the
    AORC cache.

    Empty list means the cache covers every requested year. Returns the full
    list of ``years`` when the cache isn't probeable (no AORC_S3_BASE_URL).
    """
    base = aorc_base_url or os.environ.get("AORC_S3_BASE_URL")
    if not base:
        log.info("AORC pre-flight: AORC_S3_BASE_URL not set — skipping cache check")
        return []

    parsed = urlparse(base)
    if parsed.scheme != "s3":
        log.warning(
            "AORC pre-flight: AORC_S3_BASE_URL=%s is not an s3:// URL, skipping",
            base,
        )
        return []
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/").rstrip("/")

    try:
        import boto3
    except ImportError:
        log.warning("AORC pre-flight: boto3 unavailable — skipping cache check")
        return []

    client_kwargs: dict = {"region_name": "us-east-1"}
    endpoint = os.environ.get("AORC_S3_ENDPOINT")
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
    key = os.environ.get("AORC_S3_KEY")
    secret = os.environ.get("AORC_S3_SECRET")
    if key and secret:
        client_kwargs["aws_access_key_id"] = key
        client_kwargs["aws_secret_access_key"] = secret

    s3 = boto3.client("s3", **client_kwargs)

    missing: list[int] = []
    for y in years:
        key_path = f"{prefix}/{y}.zarr/.zmetadata" if prefix else f"{y}.zarr/.zmetadata"
        try:
            s3.head_object(Bucket=bucket, Key=key_path)
        except Exception as e:
            # Treat any failure (NoSuchKey, AccessDenied, transient 5xx) as
            # "year not available". The downstream scan will produce the
            # more specific error if we're wrong about access.
            log.info(
                "AORC pre-flight: %s missing from s3://%s/%s (%s)",
                y,
                bucket,
                prefix,
                type(e).__name__,
            )
            missing.append(y)
    return missing


def assert_years_available(
    start_date: str, end_date: str | None, storm_duration_hours: int = 0
) -> None:
    """Raise RuntimeError if any year needed for ``start..end`` is unmirrored.

    Logs a clear remediation hint pointing at ``./run.py mirror``.
    """
    years = required_years(start_date, end_date, storm_duration_hours)
    if not years:
        return
    missing = verify_aorc_cache_years(years)
    if not missing:
        log.info(
            "AORC pre-flight: all %d year(s) %d-%d present in cache",
            len(years),
            years[0],
            years[-1],
        )
        return
    raise RuntimeError(
        f"AORC pre-flight: {len(missing)} year(s) missing from the private cache: "
        f"{missing}. Mirror them before launching this run: "
        f"./run.py mirror --year-start {min(missing)} --year-end {max(missing)}"
    )
