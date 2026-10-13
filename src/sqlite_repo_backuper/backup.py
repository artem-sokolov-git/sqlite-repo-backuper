import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .config import Config
from .github import GitHub
from .snapshot import gzip_file, sha256, snapshot


def run_backup(config: Config) -> str:
    """Snapshot all databases and publish them as one release; return its tag."""
    gh = GitHub(config.token)
    repo = gh.ensure_repo(config.repo)

    now = datetime.now(UTC)
    stamp = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    tag = f"backup-{stamp}"

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
