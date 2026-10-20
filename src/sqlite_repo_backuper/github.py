import base64
import time
from pathlib import Path

import httpx

from .readme import intro_text

API = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class GitHub:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            # assets go to S3 via a redirect; httpx drops the token for another origin
            follow_redirects=True,
            timeout=httpx.Timeout(60.0),
            transport=transport,
        )
        self._login: str | None = None

    def _request(self, method: str, url: str, ok: tuple[int, ...] = (), **kwargs) -> httpx.Response:
        """Send a request; raise GitHubError on failure unless the status is listed in `ok`."""
        try:
            resp = self._http.request(method, url, **kwargs)
        except httpx.HTTPError as e:
            raise GitHubError(f"{method} {url} failed: {e}") from e
        if resp.is_success or resp.status_code in ok:
            return resp
        try:
            detail = resp.json().get("message", "")
        except ValueError:
            detail = resp.text[:200]
        raise GitHubError(
            f"{method} {url} failed: HTTP {resp.status_code} {detail}".rstrip(), resp.status_code
        )

    def _paginate(self, url: str) -> list[dict]:
        items: list[dict] = []
        next_url: str | None = url
        while next_url:
            resp = self._request("GET", next_url)
            items += resp.json()
            next_url = resp.links.get("next", {}).get("url")
        return items

    def login(self) -> str:
        if self._login is None:
            self._login = self._request("GET", "/user").json()["login"]
        return self._login

    def resolve_repo(self, repo: str) -> str:
        return repo if "/" in repo else f"{self.login()}/{repo}"

    def ensure_repo(self, repo: str) -> str:
        """Make sure a private, non-empty repo exists; return its full name."""
        full = self.resolve_repo(repo)
        resp = self._request("GET", f"/repos/{full}", ok=(404,))
        if resp.status_code == 404:
            owner, name = full.split("/", 1)
            url = "/user/repos" if owner == self.login() else f"/orgs/{owner}/repos"
            self._request("POST", url, json={"name": name, "private": True})
            self._init_commit(full)
        elif not resp.json()["private"]:
            raise GitHubError(f"repository {full} is public, refusing to back up into it")
        elif self._is_empty(full):
            self._init_commit(full)
        return full

    def _is_empty(self, full: str) -> bool:
        # the repo object has no such flag; listing commits of an empty repo answers 409
        resp = self._request("GET", f"/repos/{full}/commits", ok=(409,), params={"per_page": 1})
        return resp.status_code == 409

    def _init_commit(self, full: str) -> None:
        """Seed a descriptive README; a release needs a tag, a tag needs a commit."""
        text = intro_text(full.split("/", 1)[1])
        for attempt in range(3):
            try:
                self.write_file(full, "README.md", text, "Initial commit")
                return
            except GitHubError as e:
                if attempt == 2 or e.status in (401, 403):
                    raise
                time.sleep(2)  # a just-created repository is occasionally not writable yet
                # the failed attempt may have been applied on the server
                if self.read_file(full, "README.md") is not None:
                    return

    def list_releases(self, full: str) -> list[dict]:
        """All releases including drafts (REST shape: tag_name, draft, assets, ...)."""
        return self._paginate(f"/repos/{full}/releases?per_page=100")

    def read_file(self, full: str, path: str) -> tuple[str, str] | None:
        """Return (text, blob sha) of a file in the default branch, or None if missing."""
        resp = self._request("GET", f"/repos/{full}/contents/{path}", ok=(404,))
        if resp.status_code == 404:
            return None
        data = resp.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode(), data["sha"]
        # files over 1 MB come without content; an empty text here would wipe the file
        raw = self._request(
            "GET",
            f"/repos/{full}/contents/{path}",
            headers={"Accept": "application/vnd.github.raw"},
        )
        return raw.text, data["sha"]

    def write_file(
        self, full: str, path: str, text: str, message: str, sha: str | None = None
    ) -> None:
        body = {"message": message, "content": base64.b64encode(text.encode()).decode()}
        if sha:
            body["sha"] = sha
        self._request("PUT", f"/repos/{full}/contents/{path}", json=body)

    def delete_release(self, full: str, release: dict) -> None:
        """Delete a release and, unless it is a draft, its tag."""
        self._request("DELETE", f"/repos/{full}/releases/{release['id']}", ok=(404,))
        # a draft has no tag yet; its tag_name may even belong to someone else's tag
        if not release["draft"]:
            self._request(
                "DELETE", f"/repos/{full}/git/refs/tags/{release['tag_name']}", ok=(404, 422)
            )

    def _release_by_tag(self, full: str, tag: str) -> dict:
        return self._request("GET", f"/repos/{full}/releases/tags/{tag}").json()

    def release_notes(self, full: str, tag: str) -> str:
        return self._release_by_tag(full, tag)["body"] or ""

    def download_release(self, full: str, tag: str, dest: Path) -> None:
        for asset in self._release_by_tag(full, tag)["assets"]:
            target = dest / Path(asset["name"]).name
            url = f"/repos/{full}/releases/assets/{asset['id']}"
            headers = {"Accept": "application/octet-stream"}
            try:
                with self._http.stream("GET", url, headers=headers) as resp, target.open("wb") as f:
                    if not resp.is_success:
                        raise GitHubError(
                            f"download of {asset['name']} failed: HTTP {resp.status_code}",
                            resp.status_code,
                        )
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
            except httpx.HTTPError as e:
                raise GitHubError(f"download of {asset['name']} failed: {e}") from e

    def create_release(self, full: str, tag: str, notes: str, assets: list[Path]) -> None:
        """Upload as a draft and publish only when all assets are in place."""
        release = self._request(
            "POST",
            f"/repos/{full}/releases",
            json={"tag_name": tag, "name": tag, "body": notes, "draft": True},
        ).json()
        upload_url = release["upload_url"].split("{", 1)[0]
        for asset in assets:
            with asset.open("rb") as f:
                self._request(
                    "POST",
                    upload_url,
                    params={"name": asset.name},
                    headers={
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(asset.stat().st_size),
                    },
                    content=f,
                )
        self._request("PATCH", f"/repos/{full}/releases/{release['id']}", json={"draft": False})
