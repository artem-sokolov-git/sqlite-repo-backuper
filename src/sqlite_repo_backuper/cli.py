import argparse
import sys
from pathlib import Path

from .backup import list_backups, run_backup, run_prune
from .config import ConfigError, load_config
from .github import GitHub, GitHubError
from .restore import RestoreError, run_restore
from .snapshot import SnapshotError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sqlite-repo-backuper")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="make one backup now, then apply retention")
    sub.add_parser("prune", help="delete backups outside the retention policy")
    sub.add_parser("list", help="list backups, newest first")
    restore = sub.add_parser("restore", help="restore a backup into a database file")
    restore.add_argument("target", help="backup tag or 'latest'")
    restore.add_argument("-o", "--output", type=Path, required=True)
    restore.add_argument("--db", help="database file name, if the backup holds several")
    restore.add_argument("--force", action="store_true", help="overwrite the output file")
    args = parser.parse_args(argv)

    try:
        config = load_config()
        if args.command == "backup":
            print(f"backup published: {run_backup(config)}")
            for tag in run_prune(config):
                print(f"deleted: {tag}")
        elif args.command == "prune":
            for tag in run_prune(config):
                print(f"deleted: {tag}")
        elif args.command == "list":
            gh = GitHub(config.token)
            for backup in list_backups(gh, gh.resolve_repo(config.repo)):
                print(backup.tag)
        elif args.command == "restore":
            tag = run_restore(config, args.target, args.output, args.db, args.force)
            print(f"restored {tag} to {args.output}")
    except (ConfigError, GitHubError, SnapshotError, RestoreError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
