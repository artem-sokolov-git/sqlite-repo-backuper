import gzip
import shutil
import subprocess
import tempfile
from pathlib import Path

import zstandard

COMPRESSIONS = ("gzip", "zstd", "none")
EXTENSIONS = {"gzip": ".gz", "zstd": ".zst", "none": ""}
AGE_EXTENSION = ".age"


class CompressError(Exception):
    pass


def compress(source: Path, dest: Path, kind: str) -> None:
    with source.open("rb") as f_in:
        if kind == "gzip":
            with gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        elif kind == "zstd":
            with dest.open("wb") as f_out:
                zstandard.ZstdCompressor().copy_stream(f_in, f_out)
        else:
            with dest.open("wb") as f_out:
                shutil.copyfileobj(f_in, f_out)


def decompress(source: Path, dest: Path, kind: str) -> None:
    try:
        with source.open("rb") as f_in, dest.open("wb") as f_out:
            if kind == "gzip":
                with gzip.open(f_in, "rb") as g:
                    shutil.copyfileobj(g, f_out)
            elif kind == "zstd":
                zstandard.ZstdDecompressor().copy_stream(f_in, f_out)
            else:
                shutil.copyfileobj(f_in, f_out)
    except (OSError, EOFError, zstandard.ZstdError) as e:
        raise CompressError(f"cannot decompress {source.name}: {e}") from e


def _age(*args: str) -> None:
    try:
        proc = subprocess.run(["age", *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise CompressError("age binary not found") from None
    if proc.returncode != 0:
        raise CompressError(f"age failed: {proc.stderr.strip()}")


def encrypt(source: Path, dest: Path, recipient: str) -> None:
    _age("-r", recipient, "-o", str(dest), str(source))


def decrypt(source: Path, dest: Path, identity_file: Path) -> None:
    _age("-d", "-i", str(identity_file), "-o", str(dest), str(source))


def check_recipient(recipient: str) -> None:
    """Fail fast on a missing age binary or a malformed recipient."""
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty"
        empty.touch()
        encrypt(empty, Path(tmp) / "out", recipient)


def parse_asset_name(name: str) -> tuple[str, str, bool]:
    """Split an asset name into (base name, compression kind, encrypted)."""
    encrypted = name.endswith(AGE_EXTENSION)
    if encrypted:
        name = name.removesuffix(AGE_EXTENSION)
    for kind in ("gzip", "zstd"):
        if name.endswith(EXTENSIONS[kind]):
            return name.removesuffix(EXTENSIONS[kind]), kind, encrypted
    return name, "none", encrypted
