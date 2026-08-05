import dataclasses
import sys
from pathlib import Path

import click
import git

from cli import utils


# git-based self-update service
class SelfUpdateService:
    FETCH_TIMEOUT_SECONDS = 5
    REPO_ROOT = Path(__file__).resolve().parents[2]
    REPO_NAME = "filecoin-porep-market-tooling"

    @dataclasses.dataclass
    class UpdateInfo:
        remote_name: str
        branch_name: str
        remote_sha: str
        commits_behind: int
        commits_ahead: int
        repo: git.Repo

    @staticmethod
    def _get_repo() -> git.Repo:
        return git.Repo(SelfUpdateService.REPO_ROOT, search_parent_directories=True)

    @staticmethod
    def _has_local_changes(repo: git.Repo) -> bool:
        return repo.is_dirty(untracked_files=True)

    @staticmethod
    def _get_tracking_branch(repo: git.Repo) -> git.RemoteReference | None:
        if repo.head.is_detached:
            return None

        return repo.active_branch.tracking_branch()

    @staticmethod
    def _commit_counts(repo: git.Repo, local_sha: str, remote_sha: str) -> tuple[int, int]:
        if remote_sha == local_sha:
            return 0, 0

        ahead = sum(1 for _ in repo.iter_commits(f"{remote_sha}..{local_sha}"))
        behind = sum(1 for _ in repo.iter_commits(f"{local_sha}..{remote_sha}"))

        return ahead, behind

    @staticmethod
    def check_for_update(quiet: bool) -> UpdateInfo | None:
        # noinspection PyBroadException
        try:
            repo = SelfUpdateService._get_repo()
            tracking_branch = SelfUpdateService._get_tracking_branch(repo)

            if not tracking_branch:
                if not quiet:
                    click.echo("Unable to check for updates: no tracking branch found")

                return None

            remote_name = tracking_branch.remote_name
            branch_name = tracking_branch.remote_head

        # pylint: disable=broad-exception-caught
        except Exception as e:
            if not quiet:
                click.echo(f"Unable to check for updates: {e}")

            return None

        # TODO MASTER / MAIN ONLY?
        # TODO SKIP_AUTO_UPDATE ENV VAR?

        # noinspection PyBroadException
        try:
            remote = repo.remotes[remote_name]
            remote.fetch(branch_name, kill_after_timeout=SelfUpdateService.FETCH_TIMEOUT_SECONDS)
            remote_ref = remote.refs[branch_name]
            remote_sha = remote_ref.commit.hexsha
            local_sha = repo.head.commit.hexsha

        # pylint: disable=broad-exception-caught
        except Exception as e:
            if not quiet:
                click.echo(f"Unable to fetch updates from remote '{remote_name}': {e}")

            return None

        ahead, behind = SelfUpdateService._commit_counts(repo, local_sha, remote_sha)

        if behind == 0:
            if not quiet:
                click.echo(f"{SelfUpdateService.REPO_NAME} is up to date")

            return None

        return SelfUpdateService.UpdateInfo(
            remote_name=remote_name,
            branch_name=branch_name,
            remote_sha=remote_sha,
            commits_behind=behind,
            commits_ahead=ahead,
            repo=repo
        )

    @staticmethod
    def _pull_update(update_info: UpdateInfo):
        try:
            update_info.repo.git.merge(f"{update_info.remote_name}/{update_info.branch_name}", "--ff-only")
            click.echo(f"{SelfUpdateService.REPO_NAME} updated to {update_info.remote_sha[:8]}.")
        except git.GitCommandError as e:
            click.echo(f"Self-update failed: {e}")

    # returns reason for skipping update if unsafe, or None if safe to update
    @staticmethod
    def _update_unsafe_reason(update_info: UpdateInfo) -> str | None:
        remote_ref_name = f"{update_info.remote_name}/{update_info.branch_name}"

        if update_info.commits_ahead > 0:
            return f"{update_info.commits_ahead} local commit(s) detected ahead of {remote_ref_name}"

        if SelfUpdateService._has_local_changes(update_info.repo):
            return "uncommitted local changes detected; commit or stash your changes (`git stash`) and try again"

        branch = None if update_info.repo.head.is_detached else update_info.repo.active_branch.name

        if branch != update_info.branch_name:
            where = "in detached HEAD state" if branch is None else f"on branch '{branch}'"
            return f"repository is {where}, not on '{update_info.branch_name}' anymore"

        return None

    @staticmethod
    def _prompt_and_update(update_info: UpdateInfo):
        remote_ref_name = f"{update_info.remote_name}/{update_info.branch_name}"
        update_unsafe_reason = SelfUpdateService._update_unsafe_reason(update_info)
        echo_str = (f"A new version of {SelfUpdateService.REPO_NAME} is available "
                    f"({update_info.commits_behind} commit(s) behind {remote_ref_name} @ "
                    f"{update_info.remote_sha[:8]})")

        if update_unsafe_reason:
            click.echo(f"{echo_str}, but auto-update cannot be performed:\n{update_unsafe_reason}.\n\n")

        elif utils.confirm(f"{echo_str}.\nDo you want to pull the update now?", default=True):
            SelfUpdateService._pull_update(update_info)
            click.echo("Please run the command again to use the updated version.")
            sys.exit(0)

        else:
            click.echo("\n")

    @staticmethod
    def check_and_prompt(quiet: bool):
        # noinspection PyBroadException
        try:
            update_info = SelfUpdateService.check_for_update(quiet)

            if update_info is not None:
                SelfUpdateService._prompt_and_update(update_info)

        # pylint: disable=broad-exception-caught
        except Exception as e:
            # self-update must never break the command the user actually ran
            if not quiet:
                click.echo(f"Self-update failed: {e}")
