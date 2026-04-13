"""Action: upload-outputs — Upload all processed files to remote storage."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from cc.plugin_manager import DataSourceOpInput

log = logging.getLogger(__name__)

S3_MAX_RETRIES = 3
S3_RETRY_DELAY = 2  # seconds, doubled each retry


def _s3_upload_with_retry(pm: Any, op: DataSourceOpInput, local_path: str) -> None:
    """Upload a file to S3 with exponential backoff retry."""
    delay = S3_RETRY_DELAY
    for attempt in range(1, S3_MAX_RETRIES + 1):
        try:
            pm.copy_file_to_remote(ds=op, localpath=local_path)
            return
        except Exception:
            if attempt == S3_MAX_RETRIES:
                raise
            log.warning(
                "S3 upload attempt %d/%d failed for %s, retrying in %ds",
                attempt,
                S3_MAX_RETRIES,
                local_path,
                delay,
            )
            time.sleep(delay)
            delay *= 2


def upload_outputs(ctx: dict[str, Any], action: Any) -> None:
    pm = ctx["pm"]
    payload = ctx["payload"]
    local_root: Path = ctx["local_root"]

    attrs = payload.attributes
    catalog_id = attrs["catalog_id"]
    remote_base = attrs["output_path"]
    output_dir = local_root / catalog_id

    if not output_dir.exists():
        raise FileNotFoundError(f"Output directory not found: {output_dir}")

    files = [f for f in output_dir.rglob("*") if f.is_file()]
    if not files:
        raise FileNotFoundError(f"No output files found in: {output_dir}")

    log.info("Uploading %d files to %s", len(files), remote_base)

    for output_source in payload.outputs:
        for file in files:
            rel_path = str(file.relative_to(output_dir))
            remote_path = f"{remote_base}/{rel_path}"
            output_source.paths[rel_path] = remote_path
            op = DataSourceOpInput(
                name=output_source.name, pathkey=rel_path, datakey=None
            )
            log.info("  [%s] %s -> %s", output_source.name, file.name, remote_path)
            _s3_upload_with_retry(pm, op, str(file))
