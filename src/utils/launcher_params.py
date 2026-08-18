"""Launcher identity that get_webstart_otp_v2.ashx checks the caller against.

`dependency_tools/ggm_inspect.py` resolves the official GGM version, and when
it changed, unpacks the installer and reads the launcher's assembly version,
the SHA-256 of GGMWebStart.dll, and the substitution tables that decode the
launch payload. The values below are what a released launcher reported; they
are only the starting point, and whatever the inspector last saw takes over.
"""

import asyncio
import json
import sys
from pathlib import Path

from utils.config import (
    GGM_ARTIFACT_DIR,
    GGM_INSPECT_PATH,
    LAUNCHER_CHECK_INTERVAL,
    LAUNCHER_PARAMS_PATH,
)

# Observed in GGM 1.5.0.2.
PINNED = {
    "cv": "1.5.0.2",
    "hash": "dfd568a69d87abcd8f4a93d1a4481ebb57712d1d28ab0b6fc018fcf140101e06",
    "arch": "x64",
    "tables": [
        "bac987d65e432f10",
        "3bc4d5e6f2a79108",
        "cdbeaf9012456378",
        "4e6fb81a3c5d7092",
    ],
}

_params = dict(PINNED)


def get() -> dict:
    """Current launcher parameters. Never empty - falls back to PINNED."""
    return _params


def _store(params: dict) -> None:
    _params.update(params)
    path = Path(LAUNCHER_PARAMS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_params, indent=2) + "\n", encoding="utf-8")


def load() -> None:
    """Adopt the values from an earlier run, if any."""
    path = Path(LAUNCHER_PARAMS_PATH)
    if not path.is_file():
        return
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"launcher params: ignoring unreadable {path}: {e}")
        return
    if saved.get("cv") and saved.get("hash") and saved.get("tables"):
        _params.update(saved)
        print(f"launcher params: loaded {_params['cv']} from {path}")


def _from_inspector(report: dict) -> dict:
    launcher = report["launcher"]
    tables = launcher["substitution_tables"]["data_decode_tables"]
    if len(tables) != 4:
        raise ValueError(f"expected 4 substitution tables, got {len(tables)}")
    return {
        "cv": launcher["cv"],
        "hash": launcher["hash"],
        "arch": launcher["arch"] or _params["arch"],
        "tables": list(tables),
    }


async def refresh() -> bool:
    """
    Ask the inspector whether the official launcher still matches what we send.

    Returns True when new parameters were adopted. The inspector only downloads
    and unpacks the installer when the version moved, so the common case is one
    page fetch.
    """
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        GGM_INSPECT_PATH,
        "--current-version",
        _params["cv"],
        "--arch",
        _params["arch"],
        "--output-dir",
        GGM_ARTIFACT_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            f"ggm_inspect exited {process.returncode}: {stderr.decode(errors='replace').strip()}"
        )

    report = json.loads(stdout)
    check = report.get("version_check", {})
    if "launcher" not in report:
        print(f"launcher params: {check.get('official')} unchanged")
        return False

    _store(_from_inspector(report))
    print(f"launcher params: updated to {_params['cv']} ({_params['hash'][:12]}...)")
    return True


async def refresh_loop() -> None:
    """Re-check on an interval. A failure is logged and retried next tick."""
    while True:
        await asyncio.sleep(LAUNCHER_CHECK_INTERVAL)
        try:
            await refresh()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"launcher params: check failed, retrying next tick: {e}")
