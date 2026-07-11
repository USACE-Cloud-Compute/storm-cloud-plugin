"""Tests for the Cloud Compute -> stormhub AORC credential bridge."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aorc_env import apply  # noqa: E402


def test_maps_cc_profile_to_stormhub_names():
    env = {
        "AORC_AWS_ACCESS_KEY_ID": "AK",
        "AORC_AWS_SECRET_ACCESS_KEY": "SK",
        "AORC_AWS_ENDPOINT": "https://s3.example.com",
        "AORC_AWS_DEFAULT_REGION": "us-east-1",
        "AORC_AWS_S3_BUCKET": "my-aorc-mirror",
    }
    apply(env)
    assert env["AORC_S3_KEY"] == "AK"
    assert env["AORC_S3_SECRET"] == "SK"
    assert env["AORC_S3_ENDPOINT"] == "https://s3.example.com"
    assert env["AORC_S3_REGION"] == "us-east-1"
    assert env["AORC_S3_BASE_URL"] == "s3://my-aorc-mirror"  # no prefix -> bucket root


def test_noop_without_aorc_creds():
    env = {"FFRD_AWS_ACCESS_KEY_ID": "x"}
    apply(env)
    assert "AORC_S3_KEY" not in env
    assert "AORC_S3_BASE_URL" not in env


def test_existing_aorc_s3_values_win():
    env = {"AORC_AWS_ACCESS_KEY_ID": "AK", "AORC_S3_KEY": "explicit"}
    apply(env)
    assert env["AORC_S3_KEY"] == "explicit"


def test_explicit_base_url_beats_derived():
    env = {"AORC_AWS_S3_BUCKET": "my-aorc-mirror", "AORC_S3_BASE_URL": "s3://other/x"}
    apply(env)
    assert env["AORC_S3_BASE_URL"] == "s3://other/x"


def test_prefix_is_appended_when_set():
    env = {"AORC_AWS_S3_BUCKET": "my-aorc-mirror", "AORC_S3_PREFIX": "cache/conus"}
    apply(env)
    assert env["AORC_S3_BASE_URL"] == "s3://my-aorc-mirror/cache/conus"
