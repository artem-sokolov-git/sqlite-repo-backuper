import argparse
import sys

from .backup import run_backup
from .config import ConfigError, load_config
from .github import GitHubError
from .snapshot import SnapshotError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sqlite-repo-backuper")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="make one backup now")
    args = parser.parse_args(argv)

    try:
        config = load_config()
        if args.command == "backup":
            print(f"backup published: {run_backup(config)}")
    except (ConfigError, GitHubError, SnapshotError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
