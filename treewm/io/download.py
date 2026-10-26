"""Resumable downloads driven by configs/datasets.yaml."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

import httpx
import yaml

from treewm.paths import CONFIGS, raw_dir

CHUNK = 1 << 20
TIMEOUT = httpx.Timeout(60.0, read=300.0)


def load_manifest() -> dict:
    return yaml.safe_load((CONFIGS / "datasets.yaml").read_text())


def fetch(url: str, dest: Path, expected_size: int | None = None, client: httpx.Client | None = None,
          log=print) -> Path:
    """Download url to dest, resuming a partial .part file. Verifies size when known."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (expected_size is None or dest.stat().st_size == expected_size):
        return dest
    part = dest.with_suffix(dest.suffix + ".part")
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=TIMEOUT)
    try:
        offset = part.stat().st_size if part.exists() else 0
        if expected_size is not None and offset == expected_size:
            part.replace(dest)
            return dest
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        with client.stream("GET", url, headers=headers) as r:
            if r.status_code != 416:
                r.raise_for_status()
                mode = "ab" if (offset and r.status_code == 206) else "wb"
                done = offset if mode == "ab" else 0
                next_report = done + (200 << 20)
                with open(part, mode) as f:
                    for chunk in r.iter_bytes(CHUNK):
                        f.write(chunk)
                        done += len(chunk)
                        if done >= next_report:
                            log(f"    {dest.name}: {done / 1e6:,.0f} MB")
                            next_report += 200 << 20
    finally:
        if own:
            client.close()
    size = part.stat().st_size
    if expected_size is not None and size != expected_size:
        raise IOError(f"{dest.name}: got {size} bytes, expected {expected_size}. Re-run to resume.")
    part.replace(dest)
    return dest


def _listing_links(client: httpx.Client, url: str) -> list[str]:
    html = client.get(url).text
    hrefs = re.findall(r'href="([^"?#]+)"', html)
    return [urljoin(url, h) for h in hrefs if not h.startswith("..")]


def resolve_treescope(client: httpx.Client, mirror: str, sites: list[str]) -> dict:
    files: dict = {}
    for site in sites:
        gt = f"{mirror}{site}/ground_truth/"
        stack, seen = [gt], set()
        while stack:
            url = stack.pop()
            if url in seen:
                continue
            seen.add(url)
            try:
                links = _listing_links(client, url)
            except httpx.HTTPError:
                continue
            for link in links:
                if link.endswith("/"):
                    if link.startswith(gt) and link not in seen:
                        stack.append(link)
                elif re.search(r"\.(pcd|json|png|yaml)$", link, re.I):
                    rel = link[len(mirror):]
                    files[rel] = {"url": link, "name": rel, "size": None, "default": True}
    return files


def download(dataset: str, parts: list[str] | None = None, log=print) -> list[Path]:
    manifest = load_manifest()
    if dataset not in manifest:
        raise KeyError(f"Unknown dataset {dataset}; choose from {sorted(manifest)}")
    spec = manifest[dataset]
    out = raw_dir(dataset)
    got: list[Path] = []
    with httpx.Client(follow_redirects=True, timeout=TIMEOUT) as client:
        files = spec.get("files") or {}
        if dataset == "treescope":
            files = resolve_treescope(client, spec["mirror"], spec["sites"])
        for key, f in files.items():
            if parts is not None and key not in parts:
                continue
            if parts is None and not f.get("default", False):
                continue
            dest = out / f["name"]
            log(f"[{dataset}] {key}: {f['name']} ({f.get('size') or '?'} bytes)")
            got.append(fetch(f["url"], dest, f.get("size"), client, log))
            if f.get("extract"):
                from treewm.io.extract import extract
                target = out / Path(f["name"]).name.split(".")[0]
                if not (target / ".extracted").exists():
                    log(f"[{dataset}] extracting {f['name']} -> {target}")
                    extract(dest, target, f["extract"])
    return got
