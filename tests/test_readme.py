from sqlite_repo_backuper.readme import END, START, apply_section, render_section, update_index


def _release(tag, *assets):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/o/r/releases/tag/{tag}",
        "assets": [
            {"name": n, "size": s, "browser_download_url": f"https://dl/{tag}/{n}"}
            for n, s in assets
        ],
    }


def test_render_newest_first_and_ignores_foreign_tags():
    section = render_section(
        [
            _release("backup-2026-10-12T03-00-00Z", ("app.db-x.gz", 2048)),
            _release("v1.0.0"),
            _release("backup-2026-10-13T03-00-00Z", ("a.db-y.gz", 10), ("b.db-y.gz", 5 * 1024**2)),
        ]
    )
    assert section.startswith(START) and section.endswith(END)
    assert "v1.0.0" not in section
    assert section.index("2026-10-13 03:00:00") < section.index("2026-10-12 03:00:00")
    assert "[a.db-y.gz](https://dl/backup-2026-10-13T03-00-00Z/a.db-y.gz) (10 B)" in section
    assert "<br>" in section
    assert "(2.0 KB)" in section and "(5.0 MB)" in section


def test_render_empty():
    assert "No backups yet." in render_section([])


def test_apply_section_appends_and_preserves_content():
    section = f"{START}\nnew\n{END}"
    assert apply_section("# My repo\n", section) == f"# My repo\n\n{section}\n"
    assert apply_section("", section) == f"{section}\n"


def test_apply_section_replaces_only_managed_block():
    old = f"intro\n\n{START}\nold\n{END}\n\nfooter\n"
    new = apply_section(old, f"{START}\nnew\n{END}")
    assert new == f"intro\n\n{START}\nnew\n{END}\n\nfooter\n"
    assert apply_section(new, f"{START}\nnew\n{END}") == new


def test_apply_section_ignores_markers_in_prose():
    readme = f"Docs: the list ends with `{END}`, starts with `{START}`.\n\n{START}\nold\n{END}\n"
    section = f"{START}\nnew\n{END}"
    once = apply_section(readme, section)
    assert once == f"Docs: the list ends with `{END}`, starts with `{START}`.\n\n{section}\n"
    assert apply_section(once, section) == once


def test_apply_section_appends_when_markers_only_in_prose():
    readme = f"Mentions `{END}` and `{START}` inline.\n"
    section = f"{START}\nnew\n{END}"
    once = apply_section(readme, section)
    assert once == f"{readme}\n{section}\n"
    assert apply_section(once, section) == once


class FakeGitHub:
    def __init__(self, readme):
        self.readme = readme
        self.writes = []

    def list_release_details(self, repo):
        return [_release("backup-2026-10-13T03-00-00Z", ("app.db-y.gz", 100))]

    def read_file(self, repo, path):
        return self.readme

    def write_file(self, repo, path, text, message, sha=None):
        self.writes.append((path, text, sha))


def test_update_index_writes_with_sha_then_is_idempotent():
    gh = FakeGitHub(("# repo\n", "abc123"))
    assert update_index(gh, "o/r") is True
    path, text, sha = gh.writes[0]
    assert (path, sha) == ("README.md", "abc123")
    assert text.startswith("# repo\n\n" + START)

    gh2 = FakeGitHub((text, "def456"))
    assert update_index(gh2, "o/r") is False
    assert gh2.writes == []


def test_update_index_creates_missing_readme():
    gh = FakeGitHub(None)
    assert update_index(gh, "o/r") is True
    assert gh.writes[0][2] is None


def test_intro_is_descriptive_and_combines_with_index():
    from sqlite_repo_backuper.readme import intro_text

    intro = intro_text("app-backups")
    assert intro.startswith("# app-backups\n")
    for needle in ("Releases", "backup-<UTC timestamp>", ".age", "restore latest", "public"):
        assert needle in intro
    section = render_section([])
    combined = apply_section(intro, section)
    assert combined.startswith(intro.rstrip("\n"))
    assert combined.endswith(END + "\n")
