"""E2E test configuration.

Environment isolation: e2e tests use their own env file (.env.e2e in this
directory) instead of the repo-root .env. The loading order matters:

1. cli.utils calls load_dotenv() at import time, which loads the root .env
   with override=False (it never overwrites variables already present in
   os.environ).
2. Therefore .env.e2e is loaded here with override=True BEFORE anything
   imports the cli package — its values win over both the shell and the
   root .env.
3. Every key listed in .env.e2e.example is then pre-seeded as "" if still
   unset, so the root .env cannot silently leak dev/mainnet values for keys
   the user forgot to fill in — the CLI fails with a clear "variable not
   set" error instead.

Keep .env.e2e.example in sync with the variables the CLI consumes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

E2E_DIR = Path(__file__).resolve().parent
ROOT_DIR = E2E_DIR.parent.parent.parent
ENV_FILE = E2E_DIR / ".env.e2e"
ENV_EXAMPLE_FILE = E2E_DIR / ".env.e2e.example"

# make the cli package importable when pytest is run from anywhere
sys.path.insert(0, str(ROOT_DIR))

_env_loaded = ENV_FILE.exists()
if _env_loaded:
    load_dotenv(dotenv_path=ENV_FILE, override=True)

    for line in ENV_EXAMPLE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        os.environ.setdefault(line.split("=", 1)[0], "")


@pytest.fixture(scope="session", autouse=True)
def _require_e2e_env():
    if not _env_loaded:
        pytest.skip(f"{ENV_FILE} not found — copy {ENV_EXAMPLE_FILE.name} and fill it in")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in ("true", "1", "yes") if value else default


@pytest.fixture(scope="session")
def porep_cli():
    from _utils import PorepCli

    return PorepCli(
        timeout_seconds=_env_int("E2E_TIMEOUT_SECONDS", 180),
        poll_interval_seconds=_env_int("E2E_POLL_INTERVAL_SECONDS", 3),
        echo=_env_bool("E2E_ECHO_CLI", True),
    )


@pytest.fixture
def generated_package(tmp_path):
    from _utils import create_generated_package

    package = create_generated_package(
        sptool_path=os.getenv("SPTOOL_PATH") or None,
        output_dir=tmp_path / "package",
        port=_env_int("E2E_HTTP_PORT", 18080),
        use_ngrok=_env_bool("E2E_USE_NGROK", True),
    )
    yield package
    package.stop()
