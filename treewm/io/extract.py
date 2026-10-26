"""Archive extraction with path-traversal protection."""
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path


def _check(base: Path, name: str) -> None:
    p = (base / name).resolve()
    if not p.is_relative_to(base.resolve()):
        raise ValueError(f"Unsafe path in archive: {name}")


def extract(archive: Path, target: Path, kind: str) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(archive) as z:
            for m in z.namelist():
                _check(target, m)
            z.extractall(target)
    elif kind == "7z":
        import py7zr
        with py7zr.SevenZipFile(archive, "r") as z:
            for m in z.getnames():
                _check(target, m)
            z.extractall(target)
    elif kind == "tar.zst":
        import zstandard
        with open(archive, "rb") as fh:
            dctx = zstandard.ZstdDecompressor(max_window_size=2**31)
            with dctx.stream_reader(fh) as reader:
                with tarfile.open(fileobj=reader, mode="r|") as tar:
                    tar.extractall(target, filter="data")
    else:
        raise ValueError(f"Unknown archive kind {kind}")
    (target / ".extracted").write_text(archive.name)
    return target
