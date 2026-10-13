import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .config import Config
from .github import GitHub
from .retention import Backup, make_tag, parse_tag, select_to_delete
from .snapshot import gzip_file, sha256, snapshot


def run_backup(config: Config) -> str:
    """Snapshot all databases and publish them as one release; return its tag."""
    gh = GitHub(config.token)
    repo = gh.ensure_repo(config.repo)

    now = datetime.now(UTC)
    tag = make_tag(now)
    stamp = tag.removeprefix("backup-")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        assets: list[Path] = []
        lines = [f"SQLite backup, {now.isoformat(timespec='seconds')}", "", "sha256:"]
        for db in config.db_paths:
            raw = tmp_dir / f"{db.name}.snapshot"
            snapshot(db, raw)
            asset = tmp_dir / f"{db.name}-{stamp}.gz"
            gzip_file(raw, asset)
            raw.unlink()
            assets.append(asset)
            lines.append(f"- `{asset.name}`: `{sha256(asset)}`")
        gh.create_release(repo, tag, "\n".join(lines), assets)

    return f"{repo}@{tag}"


def list_backups(gh: GitHub, repo: str) -> list[Backup]:
    """Published backups, newest first."""
    found = [
        backup
        for release in gh.list_releases(repo)
        if not release["isDraft"] and (backup := parse_tag(release["tagName"]))
    ]
    return sorted(found, key=lambda b: b.created, reverse=True)


def run_prune(config: Config) -> list[str]:
    """Delete backups outside the retention policy and leftover drafts; return deleted tags."""
    gh = GitHub(config.token)
    repo = gh.resolve_repo(config.repo)

    deleted = [
        release["tagName"]
        for release in gh.list_releases(repo)
        if release["isDraft"] and parse_tag(release["tagName"])
    ]
    deleted += [
        b.tag
        for b in select_to_delete(
            list_backups(gh, repo), config.keep_days, config.keep_weeks, config.keep_months
        )
    ]
    for tag in deleted:
        gh.delete_release(repo, tag)
    return deleted


def backup_and_prune(config: Config) -> None:
    print(f"backup published: {run_backup(config)}", flush=True)
    for tag in run_prune(config):
        print(f"deleted: {tag}", flush=True)
