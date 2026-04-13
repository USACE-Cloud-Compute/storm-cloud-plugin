#!/usr/bin/env python3
"""Task runner for storm-cloud-plugin. Requires Python 3 and Docker."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PAYLOAD = "test/examples/payload.json"


def run_cmd(args: list[str], env: dict[str, str] | None = None, **kwargs) -> None:
    merged_env = {**os.environ, **(env or {})}
    result = subprocess.run(args, env=merged_env, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)


def run_quiet(args: list[str]) -> None:
    subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_build() -> None:
    """Init submodule + build Docker image."""
    run_cmd(["git", "submodule", "update", "--init"])
    run_cmd(["docker", "compose", "build", "storm-cloud-plugin"])


def cmd_package() -> None:
    """Build Docker image and save as stormhub-cloud.tar."""
    cmd_build()
    image = "ghcr.io/usace/storm-cloud-plugin:latest"
    out = SCRIPT_DIR / "storm-cloud-plugin.tar"
    print(f"Saving {image} -> {out}")
    run_cmd(["docker", "save", "-o", str(out), image])
    print(f"Done: {out} ({out.stat().st_size // 1024 // 1024} MB)")


def cmd_lint() -> None:
    """Ruff linter + format check."""
    run_cmd(["ruff", "check", "src/"])
    run_cmd(["ruff", "format", "--check", "src/"])


def cmd_format() -> None:
    """Auto-format with ruff."""
    run_cmd(["ruff", "format", "src/"])


def cmd_freeze() -> None:
    """Regenerate constraints.txt."""
    cmd_build()
    result = subprocess.run(
        [
            "docker", "compose", "run", "--rm",
            "--entrypoint", "python3.12 -m pip freeze",
            "storm-cloud-plugin",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    skip = ("-e ", "pkg_resources", "stormhub", "cc-py-sdk", "cc_py_sdk")
    lines = sorted(
        line
        for line in result.stdout.splitlines()
        if line.strip() and not any(line.startswith(s) for s in skip)
    )
    (SCRIPT_DIR / "constraints.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print("Updated constraints.txt")


def cmd_down() -> None:
    """Stop containers."""
    run_quiet(["docker", "compose", "down", "--remove-orphans"])


def cmd_clean() -> None:
    """Remove containers, volumes, Local/."""
    cmd_down()
    shutil.rmtree(SCRIPT_DIR / "Local", ignore_errors=True)
    run_quiet(["docker", "compose", "down", "-v", "--remove-orphans"])
    print("Cleaned.")


def cmd_run(payload_file: str) -> None:
    run_cmd(["git", "submodule", "update", "--init"])
    cmd_down()

    # Container path: test/ is mounted as /inputs/ in the seed service
    container_path = "/inputs/" + payload_file.replace("\\", "/").split("test/", 1)[-1]

    print(f"Running: {payload_file}\n")
    run_cmd(
        ["docker", "compose", "run", "--rm", "seed"],
        env={"PAYLOAD_FILE": container_path},
    )
    run_cmd(["docker", "compose", "run", "--rm", "storm-cloud-plugin"])


TASK_COMMANDS = {
    "build": cmd_build,
    "package": cmd_package,
    "lint": cmd_lint,
    "format": cmd_format,
    "freeze": cmd_freeze,
    "down": cmd_down,
    "clean": cmd_clean,
}


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg in ("-h", "--help", "help"):
        print("Usage: python run.py [PAYLOAD | command]\n")
        print("  (no args)    Run with test/examples/payload.json")
        print("  PAYLOAD      Run with a custom payload file\n")
        for name in TASK_COMMANDS:
            print(f"  {name:<12} {TASK_COMMANDS[name].__doc__ or ''}")
        return

    if arg in TASK_COMMANDS:
        TASK_COMMANDS[arg]()
        return

    if arg:
        if not Path(arg).is_file():
            print(f"Error: file not found: {arg}", file=sys.stderr)
            sys.exit(1)
        payload_file = arg
    else:
        payload_file = DEFAULT_PAYLOAD

    cmd_run(payload_file)


if __name__ == "__main__":
    main()
