# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Docker container that backs up SQLite databases to a private GitHub repository on a schedule
(like docker-postgres-backup-local, but the target is GitHub). User-facing docs: `README.md`.
The original plan and design rationale: `.claude/Plan.md`.

## Commands

```sh
uv sync                                   # install deps (Python 3.13, uv only, no pip)
uv run pytest                             # all tests
uv run pytest tests/test_retention.py::test_newest_always_kept   # single test
uv run ruff format . && uv run ruff check .                      # line length 100
docker build -t sqlite-repo-backuper:dev .
uv run sqlite-repo-backuper backup        # CLI; needs SQLITE_DB_PATHS, GITHUB_REPO, GH_TOKEN in env
```

CI (`.github/workflows/release.yml`) runs `ruff check`, `ruff format --check` and `pytest`, then
builds and pushes a multi-arch image to GHCR from `main` and `v*` tags.

## Architecture

Entry point is `cli.py` (subcommands `run`, `backup`, `prune`, `list`, `restore`, `healthcheck`).
Configuration is env-only (`config.py`); every variable also accepts a `<NAME>_FILE` variant for
Docker secrets, except `HEALTH_FILE`.

GitHub is reached exclusively by shelling out to the `gh` CLI (`github.py`, token passed via the
`GH_TOKEN` env of the subprocess). There is no REST client and no git checkout.

**Storage model: one GitHub Release per backup**, tag `backup-<UTC %Y-%m-%dT%H-%M-%SZ>`, one asset
per database. Not commits: git history would grow forever, while deleting a release frees space.
The tag is the single source of truth about when a backup was made:
`retention.py` (`make_tag`/`parse_tag`) is used by the backup, prune, list and restore paths.
Releases whose tag does not parse are ignored everywhere.

Backup pipeline (`backup.py`): `ensure_repo` (creates an empty private repo and seeds it with the
descriptive README from `readme.intro_text` as the first commit, since a release needs a tag and a
tag needs a commit; seeds an existing empty repo the same way; refuses a public one) → `snapshot.py` (`sqlite3.backup()` API,
WAL-safe, then `integrity_check`) → `compress.py` (gzip/zstd/none, then optional `age` via the
`age` binary) → release is created as a **draft** and published only after all assets are
uploaded. `run_prune` also deletes leftover `backup-*` drafts from interrupted runs.

Asset names encode how to undo the pipeline: `<db>-<stamp>[.gz|.zst][.age]`.
`compress.parse_asset_name` is the inverse used by `restore.py`, which verifies the sha256 from the
release notes, decrypts (`AGE_IDENTITY`), decompresses to a temp file next to the target,
runs `integrity_check` and only then `os.replace`s it. Changing the naming scheme breaks
restore of existing backups.

After each backup/prune `readme.py` rewrites only the marker-delimited block of the backup repo's
`README.md` (via the contents API, one commit, skipped if unchanged). It must never overwrite
other README content, because the repo may be user-owned; its failure is logged, not raised.

Retention (`retention.py:select_to_delete`) is a pure function: keeps the last backup of each of
the last N days/weeks/months that have backups; the newest is never deleted. Several backups on
one day therefore collapse into one.

Daemon (`scheduler.py:run_daemon`): croniter schedule, injectable clock and stop event (tests use a
fake clock). A failing job is logged, sent to `WEBHOOK_URL` and retried on the next tick. The
health file stores a deadline (next run + 1h) and is advanced only after a success; the image's
`HEALTHCHECK` runs `healthcheck` against it.

## Testing notes

- Tests never talk to GitHub. `tests/test_github.py` fakes `subprocess.run` to check the `gh`
  arguments, but the real API behaviour of `github.py`, `ensure_repo` and the release flow is
  verified only manually against a real private repo; do that after touching them.
- `age`-dependent tests are skipped when the `age` binary is not installed locally.
- A token scoped to a single repository cannot create repositories (`Resource not accessible by
  personal access token`); auto-create needs a classic `repo` PAT or a fine-grained token with
  Administration + Contents write on all repositories.

## Docker image

`gh` and `age` are installed as static binaries on separate build stages, not via apt (the Debian
`gh` package depends on `git`/`perl` and adds ~110 MB). Versions are pinned by `ARG`; `gh` is
checked against the release checksums file, but `age` publishes none, so its per-arch sha256 is
hardcoded in the `Dockerfile` and must be recomputed when bumping `AGE_VERSION`.
The container runs as uid 1000; the database volume must be mounted read-write (SQLite needs the
`-wal`/`-shm` files).

## Git

Conventional commit messages (`feat:`, `docs:`, ...), without a `Co-Authored-By` trailer.
Commit only when asked.
