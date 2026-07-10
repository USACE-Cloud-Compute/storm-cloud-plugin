"""Bridge Cloud Compute AORC credentials to the env vars stormhub reads.

stormhub selects the AORC source from ``AORC_S3_*`` env vars (see
``stormhub.met.zarr_to_dss.aorc_storage_options``): when ``AORC_S3_KEY`` is set
it reads an authenticated S3 mirror at ``AORC_S3_ENDPOINT`` / ``AORC_S3_BASE_URL``
(with ``AORC_S3_SECRET`` and optional ``AORC_S3_REGION``); otherwise it reads the
anonymous NOAA public bucket.

Cloud Compute injects credential *profiles* as ``<PROFILE>_AWS_*`` env vars
(that is how the ``FFRD`` store creds reach the container), so an ``AORC``
profile arrives as ``AORC_AWS_ACCESS_KEY_ID`` etc. This module maps those to the
``AORC_S3_*`` names and derives ``AORC_S3_BASE_URL`` from the profile bucket
(optionally under ``AORC_S3_PREFIX``), so the mirror can be configured with a CC
credentials profile and the keys never sit in plaintext ``environment``.

``apply()`` runs on import — BEFORE stormhub is imported, because
``AORC_S3_BASE_URL`` is read at stormhub import time. It is idempotent and never
overrides values already set (so a direct ``AORC_S3_*`` environment still works),
and it is a no-op when no AORC credentials are present (anonymous NOAA public).
"""

import os

# Cloud Compute ``<profile>_AWS_*`` name -> the ``AORC_S3_*`` name stormhub reads.
_CRED_MAP = {
    "AORC_AWS_ACCESS_KEY_ID": "AORC_S3_KEY",
    "AORC_AWS_SECRET_ACCESS_KEY": "AORC_S3_SECRET",
    "AORC_AWS_ENDPOINT": "AORC_S3_ENDPOINT",
    "AORC_AWS_DEFAULT_REGION": "AORC_S3_REGION",
}


def apply(env: dict | None = None) -> None:
    """Populate ``AORC_S3_*`` from CC ``AORC_AWS_*`` creds; existing values win."""
    env = os.environ if env is None else env

    for src, dst in _CRED_MAP.items():
        value = env.get(src)
        if value and not env.get(dst):
            env[dst] = value

    # Derive the bucket URL from the profile bucket when not set directly. If the
    # year zarrs live under a bucket prefix, set AORC_S3_PREFIX; otherwise the
    # bucket root is used. AORC_S3_BASE_URL, if set, always wins.
    if not env.get("AORC_S3_BASE_URL"):
        bucket = env.get("AORC_AWS_S3_BUCKET")
        if bucket:
            prefix = env.get("AORC_S3_PREFIX", "").strip("/")
            base = f"s3://{bucket.strip('/')}"
            env["AORC_S3_BASE_URL"] = f"{base}/{prefix}" if prefix else base


apply()
