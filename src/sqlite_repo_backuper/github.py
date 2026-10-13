import base64
import json
import os
import subprocess
from pathlib import Path


class GitHubError(Exception):
    pass


class GitHub:
    def __init__(self, token: str):
        self._env = {**os.environ, "GH_TOKEN": token, "GH_PROMPT_DISABLED": "1"}

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(["gh", *args], env=self._env, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise GitHubError(f"gh {' '.join(args[:3])} failed: {proc.stderr.strip()}")
        return proc

    def login(self) -> str:
        return self._run("api", "user", "--jq", ".login").stdout.strip()

    def resolve_repo(self, repo: str) -> str:
        return repo if "/" in repo else f"{self.login()}/{repo}"

    def ensure_repo(self, repo: str) -> str:
        """Make sure a private, non-empty repo exists; return its full name."""
        full = self.resolve_repo(repo)
        proc = self._run("repo", "view", full, "--json", "isPrivate,isEmpty", check=False)
        if proc.returncode == 0:
            info = json.loads(proc.stdout)
            if not info["isPrivate"]:
                raise GitHubError(f"repository {full} is public, refusing to back up into it")
            if info["isEmpty"]:
                self._init_commit(full)
        elif "Could not resolve to a Repository" in proc.stderr:
            self._run("repo", "create", full, "--private", "--add-readme")
        else:
            raise GitHubError(f"gh repo view {full} failed: {proc.stderr.strip()}")
        return full

    def _init_commit(self, full: str) -> None:
        content = base64.b64encode(b"# SQLite backups\n").decode()
        self._run(
            "api", "-X", "PUT", f"repos/{full}/contents/README.md",
            "-f", "message=Initial commit", "-f", f"content={content}",
        )  # fmt: skip

    def create_release(self, full: str, tag: str, notes: str, assets: list[Path]) -> None:
        """Upload as a draft and publish only when all assets are in place."""
        self._run(
            "release", "create", tag, *map(str, assets),
            "--repo", full, "--title", tag, "--notes", notes, "--draft",
        )  # fmt: skip
        self._run("release", "edit", tag, "--repo", full, "--draft=false")
