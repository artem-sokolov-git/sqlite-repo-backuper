# sqlite-repo-backuper

A Docker container that backs up SQLite databases to a private GitHub repository on a schedule.
Think [docker-postgres-backup-local](https://github.com/prodrigestivill/docker-postgres-backup-local),
but the backups go to GitHub instead of a local disk.

Everything is automatic and configured through environment variables:

- creates the private repository if it does not exist (and refuses to use a public one);
- takes a consistent snapshot of a live database (WAL-safe, verified with `PRAGMA integrity_check`);
- compresses it (gzip by default, zstd optional) and optionally encrypts it with [age](https://age-encryption.org);
- publishes every backup as a GitHub Release, so deleting old backups really frees the space;
- keeps the last backup of each of the last N days, weeks and months and deletes the rest;
- restores a backup with a single command.

## Quick start

**1. Create a token.** The container needs to create the repository, upload releases and delete
old ones. Either of these works:

- a **classic** personal access token with the `repo` scope; or
- a **fine-grained** token with *Repository access: All repositories* and the repository
  permissions *Administration: Read and write* and *Contents: Read and write*.

If you create the repository yourself beforehand, a fine-grained token limited to that single
repository with only *Contents: Read and write* is enough. Such a token cannot create
repositories, so the container fails with `Resource not accessible by personal access token`
when the repository does not exist.

Save the token to a file next to your `docker-compose.yml`:

```sh
echo "<your token>" > gh_token.txt
chmod 600 gh_token.txt
```

**2. Add the container to your compose file**, next to the service that owns the database:

```yaml
services:
  app:
    image: your-app:latest
    volumes:
      - app-data:/data

  sqlite-backup:
    image: ghcr.io/OWNER/sqlite-repo-backuper:latest
    restart: unless-stopped
    user: "1000:1000"                 # the uid that owns the database files
    volumes:
      - app-data:/data                # read-write: SQLite needs access to -wal/-shm
    environment:
      SQLITE_DB_PATHS: /data/app.db   # comma-separated for several databases
      GITHUB_REPO: app-backups        # or owner/name; owner defaults to the token's user
      GH_TOKEN_FILE: /run/secrets/gh_token
      SCHEDULE: "0 3 * * *"           # cron expression or @daily, @hourly, ...
      BACKUP_ON_START: "true"
    secrets:
      - gh_token

secrets:
  gh_token:
    file: ./gh_token.txt

volumes:
  app-data:
```

A complete example is in [`docker-compose.example.yml`](docker-compose.example.yml).

**3. Start it.**

```sh
docker compose up -d sqlite-backup
docker compose logs -f sqlite-backup
```

With `BACKUP_ON_START=true` the first backup is made immediately. You will see
`backup published: owner/app-backups@backup-<timestamp>` and the repository with the release
appears on GitHub.

**4. Restore** when you need it. Stop the application first, then:

```sh
docker compose run --rm sqlite-backup restore latest -o /data/app.db --force
```

Use `restore <tag> ...` for a specific backup (see `docker compose run --rm sqlite-backup list`).
If the backup contains several databases, pick one with `--db app.db`. Restoring never leaves a
half-written file: the backup is downloaded, checksum-verified, unpacked next to the target,
integrity-checked and only then moved into place.

## Commands

| Command | What it does |
|---|---|
| `run` (default) | Runs the daemon on `SCHEDULE` |
| `backup` | Makes one backup now and applies retention |
| `prune` | Applies retention only |
| `list` | Lists backups, newest first |
| `restore <tag\|latest> -o PATH` | Restores a backup into a database file |
| `healthcheck` | Exits 0 if the daemon is on schedule (used by the image's `HEALTHCHECK`) |

## Configuration

All settings are environment variables. Every variable except `HEALTH_FILE` also accepts a
`<NAME>_FILE` variant that reads the value from a file (for Docker secrets).

| Variable | Default | Description |
|---|---|---|
| `SQLITE_DB_PATHS` | required | Paths to the databases, comma-separated |
| `GITHUB_REPO` | required | `name` or `owner/name`; without an owner the token's user is used |
| `GH_TOKEN` | required | GitHub token, see [Quick start](#quick-start) for the required permissions |
| `SCHEDULE` | `@daily` | Cron expression or `@hourly`, `@daily`, `@weekly`, `@monthly` |
| `BACKUP_ON_START` | `false` | Make a backup right when the container starts |
| `BACKUP_KEEP_DAYS` | `7` | Keep the last backup of each of the last N days |
| `BACKUP_KEEP_WEEKS` | `4` | Keep the last backup of each of the last N weeks |
| `BACKUP_KEEP_MONTHS` | `6` | Keep the last backup of each of the last N months |
| `COMPRESSION` | `gzip` | `gzip`, `zstd` or `none` |
| `AGE_RECIPIENT` | – | age public key; enables encryption of the backups |
| `AGE_IDENTITY` | – | age private key; needed by `restore` for encrypted backups |
| `WEBHOOK_URL` | – | `http(s)` URL that receives a JSON `POST` when a backup fails |
| `TZ` | `UTC` | Timezone for `SCHEDULE` |
| `HEALTH_FILE` | `/tmp/sqlite-repo-backuper.health` | Where the daemon records its health deadline |

Notes:

- The newest backup is never deleted, even if all `BACKUP_KEEP_*` are `0`.
- The webhook payload is `{"status": "error", "message": "..."}`. For healthchecks.io use your
  ping URL with `/fail` appended, otherwise the request counts as a successful ping.
- The container becomes `unhealthy` if no backup succeeded for an hour past the expected time.

## Good to know

- Retention keeps the **last** backup of each day, so several backups made on the same day
  collapse into one. Defaults: 7 days, 4 weeks, 6 months.
- A private repository is not an encrypted one. For sensitive data set `AGE_RECIPIENT` to an age
  public key and keep the matching private key (`AGE_IDENTITY` / `AGE_IDENTITY_FILE`) for restores.
- A single backup file must stay under GitHub's 2 GB release asset limit.
