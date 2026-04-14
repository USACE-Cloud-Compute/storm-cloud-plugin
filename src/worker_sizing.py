"""Pick a worker count the container can afford.

The vendored stormhub library defaults to ``os.cpu_count() - 2`` workers,
which inside a container reads the *host* CPU count and can exceed the
cgroup memory ceiling — causing OOM-driven ``BrokenProcessPool``. This
module picks a safe count from the cgroup limit, with operator overrides.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Per-worker memory budget: observed ~1–1.5 GB on trinity + 72 hr AORC;
# 2 GB absorbs transient spikes.
PER_WORKER_MB = 2048

CGROUP_MEM_MAX = "/sys/fs/cgroup/memory.max"


def resolve_num_workers(attrs: dict) -> int:
    """Payload attribute > CC_NUM_WORKERS env > cgroup-derived > 1."""
    source, n = _resolve(attrs)
    log.info("num_workers=%d (%s)", n, source)
    return n


def _resolve(attrs: dict) -> tuple[str, int]:
    if attrs.get("num_workers"):
        return "from payload attribute", max(1, int(attrs["num_workers"]))
    if os.environ.get("CC_NUM_WORKERS"):
        return "from CC_NUM_WORKERS env", max(1, int(os.environ["CC_NUM_WORKERS"]))
    mem_mb = _cgroup_mem_limit_mb()
    if mem_mb is None:
        return "cgroup unset — fallback", 1
    return "auto-sized from cgroup", max(1, mem_mb // PER_WORKER_MB)


def _cgroup_mem_limit_mb() -> int | None:
    """Read cgroup v2 ``memory.max`` in MiB, or None if unlimited/absent."""
    try:
        raw = Path(CGROUP_MEM_MAX).read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    if raw == "max":
        return None
    try:
        bytes_ = int(raw)
    except ValueError:
        return None
    # Kernel sentinels for "no limit" are huge.
    if bytes_ <= 0 or bytes_ >= (1 << 62):
        return None
    return bytes_ // (1024 * 1024)
