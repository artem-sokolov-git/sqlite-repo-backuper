import shutil
import subprocess

import pytest

from sqlite_repo_backuper.compress import (
    EXTENSIONS,
    CompressError,
    check_recipient,
    compress,
    decompress,
    decrypt,
    encrypt,
    parse_asset_name,
)

needs_age = pytest.mark.skipif(shutil.which("age") is None, reason="age is not installed")


@pytest.mark.parametrize("kind", ["gzip", "zstd", "none"])
def test_compression_roundtrip(tmp_path, kind):
    src = tmp_path / "f"
    src.write_bytes(b"hello" * 1000)
    packed = tmp_path / "packed"
    compress(src, packed, kind)
    out = tmp_path / "out"
    decompress(packed, out, kind)
    assert out.read_bytes() == b"hello" * 1000


def test_decompress_garbage(tmp_path):
    bad = tmp_path / "bad"
    bad.write_bytes(b"definitely not compressed")
    with pytest.raises(CompressError):
        decompress(bad, tmp_path / "out", "zstd")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("app.db-2026-10-13T15-26-28Z.gz", ("app.db-2026-10-13T15-26-28Z", "gzip", False)),
        ("app.db-2026-10-13T15-26-28Z.zst.age", ("app.db-2026-10-13T15-26-28Z", "zstd", True)),
        ("app.db-2026-10-13T15-26-28Z", ("app.db-2026-10-13T15-26-28Z", "none", False)),
        ("app.db-2026-10-13T15-26-28Z.age", ("app.db-2026-10-13T15-26-28Z", "none", True)),
    ],
)
def test_parse_asset_name(name, expected):
    assert parse_asset_name(name) == expected


def test_extensions_match_parser():
    for kind, ext in EXTENSIONS.items():
        assert parse_asset_name(f"x{ext}")[1] == kind


@needs_age
def test_age_roundtrip(tmp_path):
    key = tmp_path / "key"
    out = subprocess.run(["age-keygen", "-o", str(key)], capture_output=True, text=True)
    recipient = out.stderr.split("Public key: ")[1].strip()
    src = tmp_path / "plain"
    src.write_bytes(b"secret")
    encrypt(src, tmp_path / "enc", recipient)
    assert (tmp_path / "enc").read_bytes() != b"secret"
    decrypt(tmp_path / "enc", tmp_path / "dec", key)
    assert (tmp_path / "dec").read_bytes() == b"secret"


@needs_age
def test_bad_recipient():
    with pytest.raises(CompressError):
        check_recipient("not-a-key")
