import dataclasses
from pathlib import Path

import click
import git

from cli import utils

FETCH_TIMEOUT_SECONDS = 5

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclasses.dataclass
class UpdateInfo:
    remote_name: str
    branch_name: str
    remote_sha: str
    commits_behind: int
    commits_ahead: int


def _get_repo() -> git.Repo | None:
    try:
        return git.Repo(_REPO_ROOT, search_parent_directories=True)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return None


def has_local_changes(repo: git.Repo) -> bool:
    return repo.is_dirty(untracked_files=True)


def _get_tracking_branch(repo: git.Repo) -> git.RemoteReference | None:
    if repo.head.is_detached:
        return None

    try:
        return repo.active_branch.tracking_branch()
    except TypeError:
        return None


def _commit_counts(repo: git.Repo, local_sha: str, remote_sha: str) -> tuple[int, int]:
    ahead = sum(1 for _ in repo.iter_commits(f"{remote_sha}..{local_sha}"))
    behind = sum(1 for _ in repo.iter_commits(f"{local_sha}..{remote_sha}"))

    return ahead, behind


def check_for_update() -> UpdateInfo | None:
    repo = _get_repo()

    if repo is None:
        return None

    tracking_branch = _get_tracking_branch(repo)

    if tracking_branch is None:
        if repo.head.is_detached:
            click.echo("[porep-tooling] Tooling repo is in detached HEAD state - auto-update skipped.")
        else:
            click.echo(
                f"[porep-tooling] Branch '{repo.active_branch.name}' has no remote tracking branch "
                "- auto-update skipped."
            )
        return None

    remote_name = tracking_branch.remote_name
    branch_name = tracking_branch.remote_head

    try:
        remote = repo.remotes[remote_name]
        remote.fetch(branch_name, kill_after_timeout=FETCH_TIMEOUT_SECONDS)
    except Exception:
        return None

    try:
        remote_ref = remote.refs[branch_name]
    except IndexError:
        return None

    remote_sha = remote_ref.commit.hexsha
    local_sha = repo.head.commit.hexsha

    if remote_sha == local_sha:
        return None

    ahead, behind = _commit_counts(repo, local_sha, remote_sha)

    if behind == 0:
        return None

    return UpdateInfo(
        remote_name=remote_name,
        branch_name=branch_name,
        remote_sha=remote_sha,
        commits_behind=behind,
        commits_ahead=ahead,
    )


def _pull(repo: git.Repo, update_info: UpdateInfo) -> None:
    if has_local_changes(repo):
        click.echo(
            "[porep-tooling] Uncommitted local changes detected - auto-update skipped. "
            "Commit or stash your changes ('git stash') and try again."
        )
        return

    branch = None if repo.head.is_detached else repo.active_branch.name

    if branch != update_info.branch_name:
        where = "in detached HEAD state" if branch is None else f"on branch '{branch}'"
        click.echo(
            f"[porep-tooling] Tooling repo is {where}, not on '{update_info.branch_name}' anymore "
            "- auto-update skipped."
        )
        return

    try:
        repo.git.merge(f"{update_info.remote_name}/{update_info.branch_name}", "--ff-only")
    except git.GitCommandError as e:
        click.echo(f"[porep-tooling] Update failed: {e}")
        return

    click.echo(f"[porep-tooling] Updated tooling to {update_info.remote_sha[:8]}.")


def _prompt_and_apply(update_info: UpdateInfo) -> None:
    remote_ref_name = f"{update_info.remote_name}/{update_info.branch_name}"

    if update_info.commits_ahead > 0:
        click.echo(
            f"\n[porep-tooling] Local branch has diverged from {remote_ref_name} "
            f"({update_info.commits_ahead} local commit(s) not on {remote_ref_name}, "
            f"{update_info.commits_behind} commit(s) behind) - auto-update skipped, update manually."
        )
        return

    click.echo(
        f"\n[porep-tooling] A new version of the tool is available "
        f"({update_info.commits_behind} commit(s) behind {remote_ref_name}, "
        f"{update_info.remote_sha[:8]})."
    )

    if not utils.confirm("Do you want to pull the update now?", default=False):
        return

    repo = _get_repo()

    if repo is None:
        return

    _pull(repo, update_info)


def check_and_prompt() -> None:
    try:
        update_info = check_for_update()

        if update_info is not None:
            _prompt_and_apply(update_info)
    except Exception:
        # self-update must never break the command the user actually ran
        pass
