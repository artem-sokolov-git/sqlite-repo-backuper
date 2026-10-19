import base64
import json
import subprocess

import pytest

from sqlite_repo_backuper import github
from sqlite_repo_backuper.github import GitHub, GitHubError


class FakeGh:
    """Stands in for subprocess.run; `responses` maps a predicate on argv to a result."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, cmd, input=None, **kwargs):
        self.calls.append((cmd, input))
        for match, returncode, stdout, stderr in self.responses:
            if match(cmd):
                return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
        raise AssertionError(f"unexpected call: {cmd}")


@pytest.fixture
def fake(monkeypatch):
    def install(*responses):
        fake = FakeGh(*responses)
        monkeypatch.setattr(github.subprocess, "run", fake)
        monkeypatch.setattr(github.time, "sleep", lambda _: None)
        return fake

    return install


def is_put(cmd):
    return "PUT" in cmd


def is_get(cmd):
    return "PUT" not in cmd and "Accept: application/vnd.github.raw" not in cmd


def test_write_file_sends_content_on_stdin(fake):
    gh_run = fake((is_put, 0, "{}", ""))
    text = "x" * 300_000  # far over the 128 KB per-argument limit once in base64
    GitHub("t").write_file("o/r", "README.md", text, "msg", sha="abc")

    ((cmd, stdin),) = gh_run.calls
    assert max(map(len, cmd)) < 1000
    assert cmd[-2:] == ["--input", "-"]
    body = json.loads(stdin)
    assert base64.b64decode(body["content"]).decode() == text
    assert (body["message"], body["sha"]) == ("msg", "abc")


def test_write_file_without_sha(fake):
    gh_run = fake((is_put, 0, "{}", ""))
    GitHub("t").write_file("o/r", "README.md", "hi", "msg")
    assert "sha" not in json.loads(gh_run.calls[0][1])


def test_read_file_base64(fake):
    content = base64.encodebytes(b"# hello\n").decode()  # GitHub wraps lines
    fake((is_get, 0, json.dumps({"encoding": "base64", "content": content, "sha": "s1"}), ""))
    assert GitHub("t").read_file("o/r", "README.md") == ("# hello\n", "s1")


def test_read_file_large_falls_back_to_raw(fake):
    gh_run = fake(
        (is_get, 0, json.dumps({"encoding": "none", "content": "", "sha": "s2"}), ""),
        (lambda cmd: "Accept: application/vnd.github.raw" in cmd, 0, "big readme", ""),
    )
    assert GitHub("t").read_file("o/r", "README.md") == ("big readme", "s2")
    assert len(gh_run.calls) == 2


def test_read_file_missing(fake):
    fake((is_get, 1, "", "gh: Not Found (HTTP 404)"))
    assert GitHub("t").read_file("o/r", "README.md") is None


def test_init_commit_stops_when_failed_put_was_applied(fake):
    readme = json.dumps({"encoding": "base64", "content": "", "sha": "s"})
    gh_run = fake((is_put, 1, "", "connection reset"), (is_get, 0, readme, ""))
    GitHub("t")._init_commit("o/r")
    puts = [cmd for cmd, _ in gh_run.calls if is_put(cmd)]
    assert len(puts) == 1


def test_init_commit_retries_until_written(monkeypatch):
    put_results = iter([(1, "", "gh: Not Found (HTTP 404)"), (0, "{}", "")])
    puts = []

    def run(cmd, input=None, **kwargs):
        if is_put(cmd):
            puts.append(cmd)
            return subprocess.CompletedProcess(cmd, *next(put_results))
        return subprocess.CompletedProcess(cmd, 1, "", "gh: Not Found (HTTP 404)")

    monkeypatch.setattr(github.subprocess, "run", run)
    monkeypatch.setattr(github.time, "sleep", lambda _: None)
    GitHub("t")._init_commit("o/r")
    assert len(puts) == 2


def test_init_commit_does_not_retry_permission_errors(fake):
    gh_run = fake((is_put, 1, "", "Resource not accessible (HTTP 403)"))
    with pytest.raises(GitHubError, match="HTTP 403"):
        GitHub("t")._init_commit("o/r")
    assert len(gh_run.calls) == 1
