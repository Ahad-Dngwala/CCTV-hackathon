"""
Tests for the SECRET_KEY fail-fast behavior in app/config.py
(AuditReport1.md finding 1.4).

Settings() is evaluated once at import time, and app.config is already
imported (with the insecure default + DEBUG=True) by the time the rest
of the test suite runs. To actually exercise different env var
combinations we import app.config fresh in a subprocess rather than in
this process.
"""

import os
import subprocess
import sys
from pathlib import Path

MODEL1_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODEL1_ROOT.parent


def _import_config_in_subprocess(env_overrides: dict) -> subprocess.CompletedProcess:
    # Inherit the real environment (needed on Windows for python.exe's own
    # DLL search path, SystemRoot, etc. — a hardcoded PATH=/usr/bin:/bin
    # only works on Linux) and use os.pathsep so PYTHONPATH is joined
    # correctly on both Windows (";") and POSIX (":").
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(MODEL1_ROOT), str(REPO_ROOT)])
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=str(MODEL1_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def test_default_secret_key_with_debug_false_refuses_to_start():
    """The public, checked-in default must never sign real sessions."""
    result = _import_config_in_subprocess({"DEBUG": "false"})
    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_default_secret_key_with_debug_true_is_allowed():
    """Local dev / the test suite itself must keep working with zero setup."""
    result = _import_config_in_subprocess({"DEBUG": "true"})
    assert result.returncode == 0, result.stderr


def test_real_secret_key_with_debug_false_starts_fine():
    result = _import_config_in_subprocess(
        {"DEBUG": "false", "SECRET_KEY": "a-real-randomly-generated-secret"}
    )
    assert result.returncode == 0, result.stderr
