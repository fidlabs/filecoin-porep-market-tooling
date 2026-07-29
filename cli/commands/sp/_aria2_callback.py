#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import sys
from pathlib import Path

# Entry point for aria2c's --on-download-complete callback, for internal use only, calls main CLI app back.
#
# aria2c does not give this hook an interactive stdin (it's closed / not a tty), so the "Continue?"
# confirmation inside `sp claim-allocations` would otherwise hang or abort silently and the transaction
# would never be sent. We open the controlling terminal directly so the user actually sees the prompt
# and can answer it. `onboard-data` forces sequential downloads whenever this callback is wired up, so
# only one of these processes runs at a time and prompts never interleave.

_CONTROLLING_TTY_STDIN = "CONIN$" if os.name == "nt" else "/dev/tty"
_CONTROLLING_TTY_STDOUT = "CONOUT$" if os.name == "nt" else "/dev/tty"

if __name__ == "__main__":
    try:
        tty_in = open(_CONTROLLING_TTY_STDIN, "r", encoding="utf-8")
        tty_out = open(_CONTROLLING_TTY_STDOUT, "w", encoding="utf-8")
    except OSError as e:
        sys.stderr.write(
            "Cannot claim allocation: no controlling terminal available to confirm the transaction "
            f"({e}).\nRun `onboard-data --claim-allocations` from an interactive terminal, or download "
            "the piece and claim its allocation separately with `sp claim-allocations --cid`.\n"
        )
        sys.exit(1)

    with tty_in, tty_out:
        subprocess.run([
            sys.executable,
            str(Path(sys.argv[0]).parent.parent.parent.parent.resolve() / "porep_tooling_cli.py"), "sp", "claim-allocations",
            os.getenv("ARIA2C_CLAIM_ALLOCATIONS_SOFTWARE") or "",
            os.getenv("ARIA2C_DEAL_ID") or "",
            "--cars-dir", str(Path(sys.argv[3]).parent),
            "--cid", str(Path(sys.argv[3]).name.split(".car")[0])
        ], check=True, stdin=tty_in, stdout=tty_out, stderr=tty_out)
