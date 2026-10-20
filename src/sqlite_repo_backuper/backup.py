import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .compress import AGE_EXTENSION, EXTENSIONS, compress, encrypt
from .config import Config
from .github import GitHub
from .readme import update_index
from .retention import Backup, make_tag, parse_tag, select_to_delete
from .snapshot import sha256, snapshot


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
            asset = tmp_dir / f"{db.name}-{stamp}{EXTENSIONS[config.compression]}"
            compress(raw, asset, config.compression)
            raw.unlink()
            if config.age_recipient:
                encrypted = asset.with_name(asset.name + AGE_EXTENSION)
                encrypt(asset, encrypted, config.age_recipient)
                asset.unlink()
                asset = encrypted
            assets.append(asset)
            lines.append(f"- `{asset.name}`: `{sha256(asset)}`")
        gh.create_release(repo, tag, "\n".join(lines), assets)

    return f"{repo}@{tag}"


log = logging.getLogger(__name__)


def _backups(releases: list[dict]) -> list[Backup]:
    found = [
        backup
        for release in releases
        if not release["draft"] and (backup := parse_tag(release["tag_name"]))
    ]
    return sorted(found, key=lambda b: b.created, reverse=True)


def list_backups(gh: GitHub, repo: str) -> list[Backup]:
    """Published backups, newest first."""
    return _backups(gh.list_releases(repo))


def run_prune(config: Config) -> list[str]:
    """Delete backups outside the retention policy and leftover drafts; return deleted tags."""
    gh = GitHub(config.token)
    repo = gh.resolve_repo(config.repo)

    releases = gh.list_releases(repo)
    doomed = [r for r in releases if r["draft"] and parse_tag(r["tag_name"])]
    published = {r["tag_name"]: r for r in releases if not r["draft"]}
    doomed += [
        published[b.tag]
        for b in select_to_delete(
            _backups(releases), config.keep_days, config.keep_weeks, config.keep_months
        )
    ]
    for release in doomed:
        gh.delete_release(repo, release)
    return [r["tag_name"] for r in doomed]


def refresh_index(config: Config) -> None:
    """Update the backup list in the repo README; never fails a backup that already succeeded."""
    gh = GitHub(config.token)
    try:
        update_index(gh, gh.resolve_repo(config.repo))
    except Exception as e:  # the backup is already published, the README is cosmetic
        log.warning("could not update README backup list: %s", e)


def backup_and_prune(config: Config) -> None:
    print(f"backup published: {run_backup(config)}", flush=True)
    for tag in run_prune(config):
        print(f"deleted: {tag}", flush=True)
    refresh_index(config)
