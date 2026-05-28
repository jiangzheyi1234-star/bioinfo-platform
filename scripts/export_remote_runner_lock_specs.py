#!/usr/bin/env python3
"""Export linux explicit conda specs from accepted remote-runner artifacts."""

from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path


def package_urls_from_artifact(path: Path) -> list[str]:
    urls: set[str] = set()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            normalized = member.name.replace("\\", "/").strip("./")
            if "/conda-meta/" not in normalized or not normalized.endswith(".json"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            payload = json.loads(handle.read().decode("utf-8"))
            url = str(payload.get("url") or "").strip()
            if not url:
                channel = str(payload.get("channel") or "").rstrip("/")
                subdir = str(payload.get("subdir") or "linux-64").strip()
                filename = str(payload.get("fn") or "").strip()
                if channel and filename:
                    url = f"{channel}/{subdir}/{filename}"
            if url:
                urls.add(url)
    if not urls:
        raise RuntimeError(f"artifact contains no explicit package URLs: {path}")
    return sorted(urls)


def export_lock(*, archive_path: Path, lock_path: Path) -> None:
    urls = package_urls_from_artifact(archive_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("@EXPLICIT\n" + "\n".join(urls) + "\n", encoding="utf-8")
    print(f"exported {len(urls)} package URLs: {lock_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export explicit conda specs from release artifacts.")
    parser.add_argument("--resources-dir", default=str(Path("resources") / "remote-runner"))
    args = parser.parse_args()

    resources_dir = Path(args.resources_dir)
    pairs = (
        (
            resources_dir / "h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz",
            Path("config")
            / "remote-runner-conda-specs"
            / "h2ometa-remote-runner"
            / "0.1.1-control-plane"
            / "linux-64.explicit.txt",
        ),
        (
            resources_dir / "h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz",
            Path("config")
            / "remote-runner-conda-specs"
            / "h2ometa-workflow-runtime"
            / "0.1.0"
            / "linux-64.explicit.txt",
        ),
    )
    for archive_path, lock_path in pairs:
        if not archive_path.exists():
            raise SystemExit(f"release artifact missing: {archive_path}")
        export_lock(archive_path=archive_path, lock_path=lock_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
