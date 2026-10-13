import os
import re
import tempfile
from pathlib import Path

from .backup import list_backups
from .compress import CompressError, decompress, decrypt, parse_asset_name
from .config import Config
from .github import GitHub
from .snapshot import SnapshotError, check_integrity, sha256


class RestoreError(Exception):
    pass


def _pick_asset(assets: list[Path], tag: str, db: str | None) -> Path:
    if db is None:
        if len(assets) != 1:
            names = ", ".join(a.name for a in assets)
            raise RestoreError(f"{tag} has several databases, choose one with --db: {names}")
        return assets[0]
    wanted = f"{db}-{tag.removeprefix('backup-')}"
    for asset in assets:
        if parse_asset_name(asset.name)[0] == wanted:
            return asset
    raise RestoreError(f"no database named {db!r} in {tag}")


def run_restore(
    config: Config, target: str, output: Path, db: str | None = None, force: bool = False
) -> str:
    """Download a backup, verify it and atomically put it at `output`; return the tag."""
    if output.exists() and not force:
        raise RestoreError(f"{output} already exists, use --force to overwrite")

    gh = GitHub(config.token)
    repo = gh.resolve_repo(config.repo)
    if target == "latest":
        backups = list_backups(gh, repo)
        if not backups:
            raise RestoreError(f"no backups in {repo}")
        tag = backups[0].tag
    else:
        tag = target

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        gh.download_release(repo, tag, tmp_dir)
        asset = _pick_asset(sorted(p for p in tmp_dir.iterdir() if p.is_file()), tag, db)

        expected = re.search(
            rf"`{re.escape(asset.name)}`: `([0-9a-f]{{64}})`", gh.release_notes(repo, tag)
        )
        if expected and expected.group(1) != sha256(asset):
            raise RestoreError(f"sha256 mismatch for {asset.name}")

        _, compression, encrypted = parse_asset_name(asset.name)
        payload = asset
        if encrypted:
            if not config.age_identity:
                raise RestoreError(f"{asset.name} is encrypted, set AGE_IDENTITY(_FILE)")
            identity = tmp_dir / "identity.key"
            identity.touch(mode=0o600)
            identity.write_text(config.age_identity.strip() + "\n")
            payload = tmp_dir / "decrypted"
            decrypt(asset, payload, identity)

        staged = output.parent / f".{output.name}.restore"
        try:
            decompress(payload, staged, compression)
            check_integrity(staged)
            # a stale WAL from the replaced database would corrupt the restored one
            for suffix in ("-wal", "-shm"):
                Path(f"{output}{suffix}").unlink(missing_ok=True)
            os.replace(staged, output)
        except (SnapshotError, CompressError, OSError):
            staged.unlink(missing_ok=True)
            raise
    return tag
