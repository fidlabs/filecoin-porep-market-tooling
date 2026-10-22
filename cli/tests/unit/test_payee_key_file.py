import os

import click
import pytest

from cli.commands import repair_utils


@pytest.fixture
def key_file(tmp_path):
    path = tmp_path / "payee.key"
    path.write_text("not-a-real-key\n")
    path.chmod(0o600)
    return path


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_owner_only_file_is_accepted(key_file):
    assert repair_utils.secret_file_problem(key_file) is None
    repair_utils.ensure_secret_file(key_file, "payee key file")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
@pytest.mark.parametrize("mode", [0o640, 0o644, 0o604, 0o660, 0o666, 0o700 | 0o004])
def test_group_or_other_access_is_refused(key_file, mode):
    key_file.chmod(mode)

    with pytest.raises(click.ClickException, match="accessible by other users"):
        repair_utils.ensure_secret_file(key_file, "payee key file")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_file_owned_by_another_user_is_refused(key_file, monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: os.stat(key_file).st_uid + 1)

    with pytest.raises(click.ClickException, match="owned by another user"):
        repair_utils.ensure_secret_file(key_file, "payee key file")


def test_error_never_contains_the_file_contents(key_file):
    key_file.chmod(0o644)

    with pytest.raises(click.ClickException) as error:
        repair_utils.ensure_secret_file(key_file, "payee key file")

    assert "not-a-real-key" not in error.value.format_message()
