import base64
import json
import os
import subprocess
import time
from pathlib import Path

from .readme import intro_text


class GitHubError(Exception):
    pass


class GitHub:
    def __init__(self, token: str):
        self._env = {**os.environ, "GH_TOKEN": token, "GH_PROMPT_DISABLED": "1"}

    def _run(
        self, *args: str, check: bool = True, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["gh", *args], env=self._env, capture_output=True, text=True, input=stdin
        )
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
            self._run("repo", "create", full, "--private")
            self._init_commit(full)
        else:
            raise GitHubError(f"gh repo view {full} failed: {proc.stderr.strip()}")
        return full

    def _init_commit(self, full: str) -> None:
        """Seed a descriptive README; a release needs a tag, a tag needs a commit."""
        text = intro_text(full.split("/", 1)[1])
        for attempt in range(3):
            try:
                self.write_file(full, "README.md", text, "Initial commit")
                return
            except GitHubError as e:
                if attempt == 2 or "HTTP 401" in str(e) or "HTTP 403" in str(e):
                    raise
                time.sleep(2)  # a just-created repository is occasionally not writable yet
                # the failed attempt may have been applied on the server
                if self.read_file(full, "README.md") is not None:
                    return

    def list_releases(self, full: str) -> list[dict]:
        out = self._run(
            "release", "list", "--repo", full, "--limit", "1000",
            "--json", "tagName,isDraft",
        ).stdout  # fmt: skip
        return json.loads(out)

    def list_release_details(self, full: str) -> list[dict]:
        """Published releases with their assets (REST shape)."""
        out = self._run(
            "api", "--paginate", "--slurp", f"repos/{full}/releases?per_page=100"
        ).stdout
        return [r for page in json.loads(out) for r in page if not r["draft"]]

    def read_file(self, full: str, path: str) -> tuple[str, str] | None:
        """Return (text, blob sha) of a file in the default branch, or None if missing."""
        proc = self._run("api", f"repos/{full}/contents/{path}", check=False)
        if proc.returncode != 0:
            if "HTTP 404" in proc.stderr:
                return None
            raise GitHubError(f"gh api contents/{path} failed: {proc.stderr.strip()}")
        data = json.loads(proc.stdout)
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode(), data["sha"]
        # files over 1 MB come without content; an empty text here would wipe the file
        raw = self._run(
            "api", "-H", "Accept: application/vnd.github.raw", f"repos/{full}/contents/{path}"
        ).stdout
        return raw, data["sha"]

    def write_file(
        self, full: str, path: str, text: str, message: str, sha: str | None = None
    ) -> None:
        body = {"message": message, "content": base64.b64encode(text.encode()).decode()}
        if sha:
            body["sha"] = sha
        # via stdin: Linux caps a single command-line argument at 128 KB
        self._run(
            "api", "-X", "PUT", f"repos/{full}/contents/{path}", "--input", "-",
            stdin=json.dumps(body),
        )  # fmt: skip

    def delete_release(self, full: str, tag: str) -> None:
        self._run("release", "delete", tag, "--repo", full, "--yes", "--cleanup-tag")

    def release_notes(self, full: str, tag: str) -> str:
        return self._run(
            "release", "view", tag, "--repo", full, "--json", "body", "--jq", ".body"
        ).stdout

    def download_release(self, full: str, tag: str, dest: Path) -> None:
        self._run("release", "download", tag, "--repo", full, "--dir", str(dest))

    def create_release(self, full: str, tag: str, notes: str, assets: list[Path]) -> None:
        """Upload as a draft and publish only when all assets are in place."""
        self._run(
            "release", "create", tag, *map(str, assets),
            "--repo", full, "--title", tag, "--notes", notes, "--draft",
        )  # fmt: skip
        self._run("release", "edit", tag, "--repo", full, "--draft=false")
