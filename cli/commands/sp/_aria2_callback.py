#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import sys
from pathlib import Path

# Entry point for aria2c callback, for internal use only, calls main CLI app back

if __name__ == "__main__":
    subprocess.run([
        sys.executable,
        str(Path(sys.argv[0]).parent.parent.parent.parent.resolve() / "porep_tooling_cli.py"), "sp", "claim-allocations",
        os.getenv("ARIA2C_CLAIM_ALLOCATIONS_SOFTWARE") or "",
        os.getenv("ARIA2C_DEAL_ID") or "",
        "--cars-dir", str(Path(sys.argv[3]).parent),
        "--cid", str(Path(sys.argv[3]).name.split(".car")[0])
    ], check=True)
