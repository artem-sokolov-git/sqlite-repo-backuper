from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .retention import parse_tag

if TYPE_CHECKING:
    from .github import GitHub

START = "<!-- backups:start -->"
END = "<!-- backups:end -->"
README = "README.md"
_BLOCK = re.compile(rf"^{re.escape(START)}[ \t]*$.*?^{re.escape(END)}[ \t]*$", re.M | re.S)


def intro_text(name: str) -> str:
    """README seeded into a repository created by the tool."""
    return f"""# {name}

Automated backups of SQLite databases, made by **sqlite-repo-backuper**.
This repository is managed by a program: it contains no source code, the backups live in
[Releases](../../releases).

## How backups are stored

- Every backup is one **Release** tagged `backup-<UTC timestamp>`, for example
  `backup-2026-10-13T03-00-00Z`.
- Each database is one release asset named `<database>-<timestamp>[.gz|.zst][.age]`.
  `.gz` and `.zst` mean gzip and zstd compression; `.age` means the file is encrypted with
  [age](https://age-encryption.org) and cannot be restored without the matching private key.
- The SHA-256 of every asset is written in the release notes.
- Old backups are deleted automatically: the last backup of each of the last N days, weeks and
  months is kept.

## Restoring

With the backup container from your compose file (stop the application first):

```sh
docker compose run --rm sqlite-backup list
docker compose run --rm sqlite-backup restore latest -o /data/app.db --force
```

Or by hand: download the asset from a release, decrypt it if it ends with `.age`
(`age -d -i key.txt -o out file.age`), then decompress it (`gunzip` or `zstd -d`).

## Please do not

- make this repository public: the backups contain your data;
- delete or edit releases by hand, the retention policy handles cleanup;
- edit the list between the `backups:start` and `backups:end` markers below, it is rewritten
  after every backup. Anything outside the markers is yours to change.
"""


def _size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def render_section(releases: list[dict]) -> str:
    """Markdown table of published backups, newest first, wrapped in the managed markers."""
    rows = []
    for release in releases:
        backup = parse_tag(release["tag_name"])
        if backup:
            rows.append((backup, release))
    rows.sort(key=lambda row: row[0].created, reverse=True)

    lines = [START, "## Backups", ""]
    if rows:
        lines += ["| Backup (UTC) | Files |", "|---|---|"]
        for backup, release in rows:
            when = backup.created.strftime("%Y-%m-%d %H:%M:%S")
            files = "<br>".join(
                f"[{a['name']}]({a['browser_download_url']}) ({_size(a['size'])})"
                for a in release["assets"]
            )
            lines.append(f"| [{when}]({release['html_url']}) | {files} |")
    else:
        lines.append("No backups yet.")
    lines.append(END)
    return "\n".join(lines)


def apply_section(existing: str, section: str) -> str:
    """Replace the managed block, or append it; everything else is left untouched.

    Markers count only on a line of their own, so a README that mentions them in prose
    (e.g. `<!-- backups:end -->` in backticks) does not get a new block on every run.
    """
    block = _BLOCK.search(existing)
    if block:
        return existing[: block.start()] + section + existing[block.end() :]
    if not existing.strip():
        return section + "\n"
    return existing.rstrip("\n") + "\n\n" + section + "\n"


def update_index(gh: GitHub, repo: str) -> bool:
    """Refresh the backup list in the repo README; return False if nothing changed."""
    section = render_section(gh.list_release_details(repo))
    current = gh.read_file(repo, README)
    text, sha = current if current else ("", None)
    updated = apply_section(text, section)
    if updated == text:
        return False
    gh.write_file(repo, README, updated, "Update backup index", sha)
    return True
