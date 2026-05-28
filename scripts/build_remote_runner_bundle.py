from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.remote_runner.bundle import REMOTE_RUNNER_VERSION, RemoteRunnerBundleBuilder


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the remote runner artifact.")
    parser.add_argument("--version", default=REMOTE_RUNNER_VERSION)
    parser.add_argument(
        "--platform",
        default="linux-64",
        choices=("linux-64", "linux-aarch64"),
        help="Remote Linux platform this artifact targets.",
    )
    parser.add_argument(
        "--runtime-dir",
        default="",
        help="Prebuilt Linux runtime directory to embed. May also be set with H2OMETA_REMOTE_RUNNER_RUNTIME_DIR.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path("resources") / "remote-runner"),
        help="Directory where the versioned .tar.gz and .sha256 files are written.",
    )
    parser.add_argument(
        "--print-archive-only",
        action="store_true",
        help="Print only the archive path, for launch scripts that capture stdout.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runtime_raw = str(args.runtime_dir or "").strip() or str(os.environ.get("H2OMETA_REMOTE_RUNNER_RUNTIME_DIR", "") or "").strip()
    if not runtime_raw:
        raise SystemExit(
            "remote runner runtime directory required; pass --runtime-dir or set H2OMETA_REMOTE_RUNNER_RUNTIME_DIR"
        )
    built = RemoteRunnerBundleBuilder().build(
        version=args.version,
        platform=args.platform,
        runtime_dir=Path(runtime_raw),
    )
    target = output_dir / f"h2ometa-remote-runner-{args.version}-{args.platform}.tar.gz"
    shutil.copyfile(built.archive_path, target)

    digest = _sha256_file(target)
    checksum_path = Path(str(target) + ".sha256")
    checksum_path.write_text(f"{digest}  {target.name}\n", encoding="utf-8")

    if args.print_archive_only:
        print(target)
    else:
        print(target)
        print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
