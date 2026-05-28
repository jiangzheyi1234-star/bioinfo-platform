from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.remote_runner.artifact import WORKFLOW_RUNTIME_VERSION


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Package a prebuilt workflow runtime artifact.")
    parser.add_argument("--version", default=WORKFLOW_RUNTIME_VERSION)
    parser.add_argument("--platform", default="linux-64", choices=("linux-64", "linux-aarch64"))
    parser.add_argument(
        "--env-dir",
        required=True,
        help="Prebuilt Linux conda-pack-compatible environment directory containing bin/snakemake and bin/conda-unpack.",
    )
    parser.add_argument(
        "--snakemake-version",
        default="",
        help="Snakemake version to record in the artifact manifest.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path("resources") / "remote-runner"),
        help="Directory where the versioned .tar.gz and .sha256 files are written.",
    )
    args = parser.parse_args()

    env_dir = Path(args.env_dir)
    if not (env_dir / "bin" / "snakemake").exists():
        raise SystemExit(f"workflow runtime env missing bin/snakemake: {env_dir}")
    env_python = env_dir / "bin" / "python"
    if not env_python.exists():
        raise SystemExit(f"workflow runtime env missing bin/python: {env_dir}")
    if not (env_dir / "bin" / "conda").exists():
        raise SystemExit(f"workflow runtime env missing bin/conda required by Snakemake --use-conda: {env_dir}")
    conda_pack = env_dir / "bin" / "conda-pack"
    if not conda_pack.exists():
        raise SystemExit(f"workflow runtime env missing bin/conda-pack: {env_dir}")
    subprocess.run([str(env_python), "-c", "import snakemake"], check=True)
    snakemake_version = str(args.snakemake_version or "").strip()
    snakemake_version_result = subprocess.run(
        [str(env_dir / "bin" / "snakemake"), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    if not snakemake_version:
        version_lines = snakemake_version_result.stdout.strip().splitlines()
        snakemake_version = version_lines[0].strip() if version_lines else ""
    if not snakemake_version:
        raise SystemExit("workflow runtime env produced an empty Snakemake version")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    root = Path(tempfile.mkdtemp(prefix="h2ometa-workflow-runtime-"))
    bundle_dir = root / "bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    packed_env = root / "workflow-env.tar.gz"
    subprocess.run(
        [str(conda_pack), "-p", str(env_dir), "-o", str(packed_env), "--force"],
        check=True,
    )
    workflow_env_dir = bundle_dir / "workflow-env"
    workflow_env_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(packed_env, "r:gz") as archive:
        archive.extractall(workflow_env_dir)
    if not (workflow_env_dir / "bin" / "conda-unpack").exists():
        raise SystemExit("conda-pack output missing workflow-env/bin/conda-unpack")
    if not any(workflow_env_dir.glob("lib/*/site-packages/snakemake/__init__.py")):
        raise SystemExit("conda-pack output missing workflow-env site-packages/snakemake")

    manifest = {
        "service": "h2ometa-workflow-runtime",
        "version": args.version,
        "platform": args.platform,
        "provider": "conda-pack",
        "entrypoints": {
            "python": "workflow-env/bin/python",
            "conda": "workflow-env/bin/conda",
            "condaUnpack": "workflow-env/bin/conda-unpack",
            "snakemake": "workflow-env/bin/snakemake",
        },
        "packages": {"snakemake": snakemake_version},
    }
    (bundle_dir / "bootstrap_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    target = output_dir / f"h2ometa-workflow-runtime-{args.version}-{args.platform}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(bundle_dir, arcname=".")
    digest = _sha256_file(target)
    checksum_path = Path(str(target) + ".sha256")
    checksum_path.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(target)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
