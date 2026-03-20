from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".ini",
    ".cfg",
    ".bat",
    ".ps1",
    ".sh",
}

SKIP_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    "__pycache__",
    "build",
    "dist",
    ".codex",
    ".claude",
    ".agents",
}


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in DEFAULT_EXTENSIONS:
            continue
        files.append(path)
    return files


def detect_and_convert(raw: bytes) -> tuple[bytes, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:], "utf-8-bom"

    try:
        raw.decode("utf-8")
        return raw, "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        text = raw.decode("gb18030")
        return text.encode("utf-8"), "gb18030"
    except UnicodeDecodeError:
        return raw, "unknown"


def process_file(path: Path, fix: bool) -> tuple[bool, str]:
    raw = path.read_bytes()
    converted, source = detect_and_convert(raw)

    if source == "unknown":
        return False, "unknown-encoding"

    if converted == raw and source == "utf-8":
        return True, "ok"

    if fix:
        path.write_bytes(converted)
        return True, f"fixed-from-{source}"
    return False, f"needs-fix-from-{source}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect/fix non UTF-8 files.")
    parser.add_argument("--fix", action="store_true", help="Rewrite files to UTF-8 without BOM.")
    parser.add_argument("--root", default=".", help="Project root path.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    files = iter_files(root)

    bad: list[tuple[Path, str]] = []
    fixed = 0
    for f in files:
        ok, status = process_file(f, fix=args.fix)
        if status.startswith("fixed-"):
            fixed += 1
        if not ok and status != "ok":
            bad.append((f, status))

    if args.fix:
        print(f"[encoding-guard] scanned={len(files)} fixed={fixed} unresolved={len(bad)}")
    else:
        print(f"[encoding-guard] scanned={len(files)} issues={len(bad)}")

    for f, status in bad:
        print(f"{status}: {f}")

    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
