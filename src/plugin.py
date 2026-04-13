"""StormHub Cloud Compute plugin entry point.

Initializes the PluginManager, validates the payload, and dispatches actions.
"""

from __future__ import annotations

import logging
import logging.config
import multiprocessing
import os
import shutil
import signal
import sys
import time
from enum import IntEnum
from pathlib import Path
from typing import Any

from cc.plugin_manager import PluginManager
from stormhub.logger import initialize_logger

from actions.download_inputs import download_inputs
from actions.process_storms import process_storms
from actions.convert_to_dss import convert_to_dss
from actions.upload_outputs import upload_outputs


def _configure_logging() -> None:
    """Configure logging — JSON in production, plain text locally."""
    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    if os.environ.get("LOG_FORMAT", "").lower() == "json":
        # Structured JSON for CloudWatch / ELK / production
        logging.config.dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "json": {
                        "format": '{"time":"%(asctime)s","level":"%(levelname)s",'
                        '"logger":"%(name)s","message":"%(message)s"}',
                        "datefmt": "%Y-%m-%dT%H:%M:%S",
                    },
                },
                "handlers": {
                    "console": {
                        "class": "logging.StreamHandler",
                        "formatter": "json",
                        "stream": "ext://sys.stdout",
                    },
                },
                "root": {"level": level, "handlers": ["console"]},
            }
        )
    else:
        initialize_logger(level=getattr(logging, level, logging.INFO))


_configure_logging()
log = logging.getLogger(__name__)

try:
    multiprocessing.set_start_method("spawn")
except RuntimeError:
    pass


class ExitCode(IntEnum):
    SUCCESS = 0
    CRITICAL = 1
    INVALID_PAYLOAD = 2
    DOWNLOAD_ERROR = 3
    PROCESSING_ERROR = 4


REQUIRED_ATTRS = ["catalog_id", "catalog_description", "output_path", "start_date"]
REQUIRED_INPUT_KEYS = ["watershed", "transposition"]

ACTION_DISPATCH = {
    "download-inputs": download_inputs,
    "process-storms": process_storms,
    "convert-to-dss": convert_to_dss,
    "upload-outputs": upload_outputs,
}

# Attribute type constraints: (validator_fn, human description)
_POSITIVE_INT = (lambda v: v.isdigit() and int(v) > 0, "positive integer string")
_NON_NEGATIVE_FLOAT = (
    lambda v: _is_non_negative_float(v),
    "non-negative numeric string",
)
_DATE_FMT = (lambda v: _is_iso_date(v), "YYYY-MM-DD date string")
_JSON_LIST = (lambda v: _is_json_string_list(v), "JSON array of date strings")

ATTR_VALIDATORS: dict[str, tuple] = {
    "start_date": _DATE_FMT,
    "end_date": _DATE_FMT,
    "storm_duration": _POSITIVE_INT,
    "top_n_events": _POSITIVE_INT,
    "check_every_n_hours": _POSITIVE_INT,
    "min_precip_threshold": _NON_NEGATIVE_FLOAT,
    "specific_dates": _JSON_LIST,
}


def _is_iso_date(v: str) -> bool:
    import re

    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v))


def _is_non_negative_float(v: str) -> bool:
    try:
        return float(v) >= 0
    except ValueError:
        return False


def _is_json_string_list(v: str) -> bool:
    import json

    try:
        parsed = json.loads(v)
        return isinstance(parsed, list) and all(isinstance(d, str) for d in parsed)
    except (json.JSONDecodeError, TypeError):
        return False


def validate_payload(payload: Any) -> None:
    """Fail fast with clear messages if payload is misconfigured."""
    attrs = payload.attributes
    missing = [k for k in REQUIRED_ATTRS if k not in attrs]
    if missing:
        raise ValueError(f"Missing required payload attributes: {missing}")

    # All attribute values must be strings (CC SDK convention)
    non_string = [k for k, v in attrs.items() if not isinstance(v, str)]
    if non_string:
        raise ValueError(
            f"All payload attribute values must be strings (CC SDK convention), "
            f"but these are not: {non_string}"
        )

    # Validate types/formats for known attributes
    errors: list[str] = []
    for key, (check_fn, description) in ATTR_VALIDATORS.items():
        value = attrs.get(key)
        if value is None or value == "":
            continue  # optional, skip
        if not check_fn(value):
            errors.append(f"  {key}={value!r} — expected {description}")
    if errors:
        raise ValueError("Invalid payload attribute values:\n" + "\n".join(errors))

    if not payload.outputs:
        raise ValueError("Payload has no outputs configured")
    if not payload.inputs:
        raise ValueError("Payload has no inputs configured")

    input_keys = payload.inputs[0].paths
    missing_keys = [k for k in REQUIRED_INPUT_KEYS if k not in input_keys]
    if missing_keys:
        raise ValueError(f"Missing required input path keys: {missing_keys}")


def run_actions(pm: PluginManager, payload: Any) -> None:
    """Dispatch each action in the payload by name."""
    local_root = Path("Local")
    local_root.mkdir(parents=True, exist_ok=True)

    interrupted = False
    succeeded = False

    def handle_signal(signum: int, frame: Any) -> None:
        nonlocal interrupted
        log.warning("Received signal %d, will shut down after current action", signum)
        interrupted = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Track completed actions for checkpoint/resume
    checkpoint_file = local_root / ".checkpoint"
    completed_actions: set[str] = set()
    if checkpoint_file.exists():
        completed_actions = set(checkpoint_file.read_text().splitlines())
        log.info("Resuming from checkpoint — already completed: %s", completed_actions)

    # Shared context passed to all actions
    ctx: dict[str, Any] = {
        "pm": pm,
        "payload": payload,
        "local_root": local_root,
        "_start_time": time.monotonic(),
    }

    try:
        for i, action in enumerate(payload.actions):
            if interrupted:
                log.warning("Shutdown requested, aborting after action %d", i)
                raise KeyboardInterrupt

            handler = ACTION_DISPATCH.get(action.name)
            if handler is None:
                log.error(
                    "Unknown action: %s (available: %s)",
                    action.name,
                    list(ACTION_DISPATCH.keys()),
                )
                raise ValueError(f"Unknown action: {action.name}")

            if action.name in completed_actions:
                log.info(
                    "[%d/%d] Skipping action (already completed): %s",
                    i + 1,
                    len(payload.actions),
                    action.name,
                )
                continue

            log.info(
                "[%d/%d] Running action: %s", i + 1, len(payload.actions), action.name
            )
            t0 = time.monotonic()
            handler(ctx, action)
            elapsed = time.monotonic() - t0
            log.info(
                "Action %s completed in %.1fs",
                action.name,
                elapsed,
            )

            # Checkpoint after each successful action
            completed_actions.add(action.name)
            checkpoint_file.write_text(
                "\n".join(sorted(completed_actions)), encoding="utf-8"
            )

        succeeded = True
        total_elapsed = time.monotonic() - ctx["_start_time"]
        log.info("All actions completed successfully in %.1fs", total_elapsed)
    finally:
        if succeeded and local_root.exists():
            shutil.rmtree(local_root)
            log.info("Cleaned up %s", local_root)
        elif local_root.exists():
            log.warning(
                "Preserving %s for debugging (run failed or interrupted)", local_root
            )


def main() -> None:
    pm = PluginManager()
    payload = pm.get_payload()
    validate_payload(payload)
    run_actions(pm, payload)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.warning("Plugin interrupted")
        sys.exit(ExitCode.CRITICAL)
    except ValueError as e:
        log.error("Invalid payload: %s", e)
        sys.exit(ExitCode.INVALID_PAYLOAD)
    except FileNotFoundError as e:
        log.error("Missing file: %s", e)
        sys.exit(ExitCode.DOWNLOAD_ERROR)
    except Exception as e:
        log.error("Plugin failed: %s", e, exc_info=True)
        sys.exit(ExitCode.PROCESSING_ERROR)
