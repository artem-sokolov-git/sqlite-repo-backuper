import base64
import json

import httpx
import pytest

from sqlite_repo_backuper import github
from sqlite_repo_backuper.github import GitHub, GitHubError


class FakeApi:
    """httpx transport; `routes` maps (method, path) to a status and a body or a handler."""

    def __init__(self, routes):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        route = self.routes.get((request.method, request.url.path))
        if route is None:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        if callable(route):
            return route(request)
        status, body = route
        if isinstance(body, bytes | str):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    def calls(self, method, path=None):
        return [
            r for r in self.requests if r.method == method and (path is None or r.url.path == path)
        ]


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(github.time, "sleep", lambda _: None)

    def install(routes):
        fake = FakeApi(routes)
        return fake, GitHub("tok", transport=httpx.MockTransport(fake))

    return install


CONTENTS = "/repos/o/r/contents/README.md"
NOT_FOUND = (404, {"message": "Not Found"})


def test_auth_header_and_login_cached(api):
    fake, gh = api({("GET", "/user"): (200, {"login": "me"})})
    assert gh.resolve_repo("r") == "me/r"
    assert gh.resolve_repo("r") == "me/r"
    assert gh.resolve_repo("other/r") == "other/r"
    ((req,),) = [fake.requests]
    assert req.headers["Authorization"] == "Bearer tok"


def test_write_file(api):
    fake, gh = api({("PUT", CONTENTS): (200, {})})
    gh.write_file("o/r", "README.md", "x" * 300_000, "msg", sha="abc")
    gh.write_file("o/r", "README.md", "hi", "msg")
    first, second = (json.loads(r.content) for r in fake.requests)
    assert base64.b64decode(first["content"]).decode() == "x" * 300_000
    assert (first["message"], first["sha"]) == ("msg", "abc")
    assert "sha" not in second


def test_read_file_base64(api):
    content = base64.encodebytes(b"# hello\n").decode()  # GitHub wraps lines
    _, gh = api({("GET", CONTENTS): (200, {"encoding": "base64", "content": content, "sha": "s1"})})
    assert gh.read_file("o/r", "README.md") == ("# hello\n", "s1")


def test_read_file_large_falls_back_to_raw(api):
    def contents(request):
        if request.headers["Accept"] == "application/vnd.github.raw":
            return httpx.Response(200, text="big readme")
        return httpx.Response(200, json={"encoding": "none", "content": "", "sha": "s2"})

    fake, gh = api({("GET", CONTENTS): contents})
    assert gh.read_file("o/r", "README.md") == ("big readme", "s2")
    assert len(fake.requests) == 2


def test_read_file_missing(api):
    _, gh = api({("GET", CONTENTS): NOT_FOUND})
    assert gh.read_file("o/r", "README.md") is None


def test_error_carries_status_and_message(api):
    _, gh = api({("GET", CONTENTS): (500, {"message": "boom"})})
    with pytest.raises(GitHubError, match="HTTP 500 boom") as e:
        gh.read_file("o/r", "README.md")
    assert e.value.status == 500


def test_network_error_becomes_github_error():
    def fail(request):
        raise httpx.ConnectError("connection reset")

    gh = GitHub("t", transport=httpx.MockTransport(fail))
    with pytest.raises(GitHubError, match="connection reset"):
        gh.login()


def test_init_commit_stops_when_failed_put_was_applied(api):
    readme = {"encoding": "base64", "content": "", "sha": "s"}
    fake, gh = api({("PUT", CONTENTS): (502, "bad gateway"), ("GET", CONTENTS): (200, readme)})
    gh._init_commit("o/r")
    assert len(fake.calls("PUT")) == 1


def test_init_commit_retries_until_written(api):
    statuses = iter([404, 201])
    fake, gh = api(
        {
            ("PUT", CONTENTS): lambda r: httpx.Response(next(statuses), json={}),
            ("GET", CONTENTS): NOT_FOUND,
        }
    )
    gh._init_commit("o/r")
    assert len(fake.calls("PUT")) == 2


def test_init_commit_does_not_retry_permission_errors(api):
    fake, gh = api({("PUT", CONTENTS): (403, {"message": "Resource not accessible"})})
    with pytest.raises(GitHubError, match="HTTP 403"):
        gh._init_commit("o/r")
    assert len(fake.requests) == 1


def test_ensure_repo_creates_private_repo_and_seeds_it(api):
    fake, gh = api(
        {
            ("GET", "/user"): (200, {"login": "me"}),
            ("GET", "/repos/me/r"): NOT_FOUND,
            ("POST", "/user/repos"): (201, {}),
            ("PUT", "/repos/me/r/contents/README.md"): (201, {}),
        }
    )
    assert gh.ensure_repo("r") == "me/r"
    (create,) = fake.calls("POST")
    assert json.loads(create.content) == {"name": "r", "private": True}


def test_ensure_repo_in_org(api):
    fake, gh = api(
        {
            ("GET", "/user"): (200, {"login": "me"}),
            ("GET", "/repos/org/r"): NOT_FOUND,
            ("POST", "/orgs/org/repos"): (201, {}),
            ("PUT", "/repos/org/r/contents/README.md"): (201, {}),
        }
    )
    gh.ensure_repo("org/r")
    assert fake.calls("POST", "/orgs/org/repos")


def test_ensure_repo_refuses_public(api):
    _, gh = api({("GET", "/repos/o/r"): (200, {"private": False})})
    with pytest.raises(GitHubError, match="public"):
        gh.ensure_repo("o/r")


@pytest.mark.parametrize("commits_status, seeded", [(409, True), (200, False)])
def test_ensure_repo_seeds_only_empty_repo(api, commits_status, seeded):
    fake, gh = api(
        {
            ("GET", "/repos/o/r"): (200, {"private": True}),
            ("GET", "/repos/o/r/commits"): (commits_status, [] if seeded else [{}]),
            ("PUT", CONTENTS): (201, {}),
        }
    )
    gh.ensure_repo("o/r")
    assert bool(fake.calls("PUT")) == seeded


def test_list_releases_follows_pagination(api):
    def releases(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"tag_name": "b"}])
        link = '<https://api.github.com/repos/o/r/releases?per_page=100&page=2>; rel="next"'
        return httpx.Response(200, json=[{"tag_name": "a"}], headers={"Link": link})

    _, gh = api({("GET", "/repos/o/r/releases"): releases})
    assert [r["tag_name"] for r in gh.list_releases("o/r")] == ["a", "b"]


def test_create_release_uploads_assets_before_publishing(api, tmp_path):
    asset = tmp_path / "app.db-x.gz"
    asset.write_bytes(b"payload")
    upload = "https://uploads.github.com/repos/o/r/releases/7/assets{?name,label}"
    fake, gh = api(
        {
            ("POST", "/repos/o/r/releases"): (201, {"id": 7, "upload_url": upload}),
            ("POST", "/repos/o/r/releases/7/assets"): (201, {}),
            ("PATCH", "/repos/o/r/releases/7"): (200, {}),
        }
    )
    gh.create_release("o/r", "backup-t", "notes", [asset])

    create, up, publish = fake.requests
    assert json.loads(create.content) == {
        "tag_name": "backup-t", "name": "backup-t", "body": "notes", "draft": True
    }  # fmt: skip
    assert up.url.host == "uploads.github.com"
    assert up.url.params["name"] == "app.db-x.gz"
    assert up.content == b"payload"
    assert json.loads(publish.content) == {"draft": False}


@pytest.mark.parametrize("draft", [False, True])
def test_delete_release_cleans_up_tag_only_when_published(api, draft):
    fake, gh = api(
        {
            ("DELETE", "/repos/o/r/releases/7"): (204, b""),
            ("DELETE", "/repos/o/r/git/refs/tags/backup-t"): (204, b""),
        }
    )
    gh.delete_release("o/r", {"id": 7, "tag_name": "backup-t", "draft": draft})
    assert bool(fake.calls("DELETE", "/repos/o/r/git/refs/tags/backup-t")) == (not draft)


def test_download_release_drops_token_on_redirect(api, tmp_path):
    fake, gh = api(
        {
            ("GET", "/repos/o/r/releases/tags/backup-t"): (
                200,
                {"assets": [{"id": 3, "name": "app.db-x.gz"}]},
            ),
            ("GET", "/repos/o/r/releases/assets/3"): lambda r: httpx.Response(
                302, headers={"Location": "https://objects.example.com/blob"}
            ),
            ("GET", "/blob"): (200, b"payload"),
        }
    )
    gh.download_release("o/r", "backup-t", tmp_path)
    assert (tmp_path / "app.db-x.gz").read_bytes() == b"payload"
    asset_req, blob_req = fake.requests[1:]
    assert asset_req.headers["Accept"] == "application/octet-stream"
    assert "Authorization" not in blob_req.headers
