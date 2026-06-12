"""In-process invocation of the porep tooling CLI for e2e tests."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class CliResult:
    output: str
    stderr: str
    exit_code: int


class PorepCli:
    """Invokes the porep tooling CLI in-process via click's CliRunner."""

    def __init__(self, *, timeout_seconds: int = 180, poll_interval_seconds: int = 3, echo: bool = True):
        # deferred import: conftest must load .env.e2e before the cli package
        # is imported (cli.utils calls load_dotenv at import time)
        from click.testing import CliRunner
        from cli import cli

        self._cli = cli
        self._runner = CliRunner(mix_stderr=False)
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.echo = echo

    def invoke(
        self,
        args: list[str],
        *,
        auto_confirm: bool = False,
        confirm_answers: list[str] | None = None,
        check: bool = True,
        echo: bool | None = None,
    ) -> CliResult:
        stdin = None
        if confirm_answers is not None:
            stdin = "".join(f"{answer}\n" for answer in confirm_answers) + "yes\n" * 255
        elif auto_confirm:
            stdin = "yes\n" * 255

        result = self._runner.invoke(self._cli, args, input=stdin, catch_exceptions=False)

        # CliRunner swallows the command's stdout/stderr into the result, so
        # re-emit it; pytest decides whether it shows up live (-s) or only in
        # the captured-output section of a failure report
        if self.echo if echo is None else echo:
            print(f"$ cli {' '.join(args)}")
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="")

        if check and result.exit_code != 0:
            raise RuntimeError(
                f"CLI command failed ({result.exit_code}): {' '.join(args)}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

        return CliResult(output=result.stdout, stderr=result.stderr, exit_code=result.exit_code)

    def invoke_json(self, args: list[str], *, echo: bool | None = None) -> Any:
        return json.loads(self.invoke(args, echo=echo).output)

    def wait_until(
        self,
        args: list[str],
        condition: Callable[[Any], bool] | None = None,
        *,
        timeout_seconds: int | None = None,
        poll_interval_seconds: int | None = None,
        description: str | None = None,
    ) -> Any:
        """Poll a JSON-printing CLI command until condition(value) is true,
        return that value. Without a condition the value's truthiness decides.
        """
        condition = condition or bool
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        poll_interval = poll_interval_seconds if poll_interval_seconds is not None else self.poll_interval_seconds
        description = description or " ".join(args)
        deadline = time.time() + timeout

        while time.time() < deadline:
            # echo off — polling the same command every few seconds would
            # drown the transcript
            value = self.invoke_json(args, echo=False)
            if condition(value):
                return value
            time.sleep(poll_interval)

        raise TimeoutError(f"Timed out after {timeout}s waiting for: {description}")
