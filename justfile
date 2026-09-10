# porep-market-tooling task runner
# Run `just` to see all available commands
set dotenv-load

pylint:
    #!/usr/bin/env bash
    set -uo pipefail
    pylint cli
    pylint_exit=$?
    if [ $((pylint_exit & 3)) -ne 0 ]; then
        exit $pylint_exit
    fi
    exit 0

flake8:
    flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
    flake8 . --count --exit-zero --statistics

ruff:
    ruff check .

lint: pylint flake8 ruff
    @echo "All linters passed."

test-sh:
    chmod +x cli/tests/test.sh && cli/tests/test.sh

check: lint test-sh
    @echo "All checks passed."

pre-push: check
    @echo "Ready to push."
