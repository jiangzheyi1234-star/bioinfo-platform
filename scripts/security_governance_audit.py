from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_BYTES = 2_000_000

SECRET_PATH_RE = re.compile(
    r"(^|/)(\.env($|\.)|id_rsa$|id_dsa$|id_ecdsa$|id_ed25519$|.*\.(pem|p12|pfx|key)$)",
    re.IGNORECASE,
)
SKIP_PATH_PARTS = {
    ".git",
    ".next",
    ".venv",
    ".venv-win",
    "node_modules",
    "__pycache__",
}
PLACEHOLDER_RE = re.compile(
    r"(example|placeholder|dummy|sample|test|phase|canary|redacted|"
    r"runner://|\$\{\{|<[^>]+>|your-|changeme|not-a-secret)",
    re.IGNORECASE,
)
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key-block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("aws-access-key-id", re.compile(r"\bA[KS]IA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{30,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{80,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    (
        "quoted-secret-assignment",
        re.compile(
            r"(?i)\b(secret|token|password|api[_-]?key|auth[_-]?secret|private[_-]?key)\b"
            r"\s*[:=]\s*[\"']([^\"'\n]{16,})[\"']"
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    line: int
    detail: str

    def format(self) -> str:
        suffix = f":{self.line}" if self.line else ""
        return f"{self.code}: {self.path}{suffix} {self.detail}".rstrip()


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=False,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        path = ROOT / relative
        if any(part in SKIP_PATH_PARTS for part in Path(relative).parts):
            continue
        paths.append(path)
    return paths


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def is_placeholder(value: str, path: str) -> bool:
    if PLACEHOLDER_RE.search(value):
        return True
    if path.startswith("tests/") and re.search(r"(token|secret|password|key)", value, re.IGNORECASE):
        return True
    return False


def scan_secrets(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if SECRET_PATH_RE.search(relative) and not relative.endswith((".env.example", ".example")):
            findings.append(Finding("tracked-secret-path", relative, 0, "tracked secret-like file path"))

        text = read_text(path)
        if text is None:
            continue
        for code, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(2) if code == "quoted-secret-assignment" else match.group(0)
                if is_placeholder(value, relative):
                    continue
                findings.append(
                    Finding(
                        code,
                        relative,
                        line_number(text, match.start()),
                        "potential committed secret; use a placeholder or secret store",
                    )
                )
    return findings


def scan_security_contracts() -> list[Finding]:
    findings: list[Finding] = []
    api_main = (ROOT / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    if 'allow_origins=["*"]' in api_main or "allow_origin_regex" in api_main:
        findings.append(Finding("cors-wildcard", "apps/api/main.py", 0, "local API CORS must use explicit origins"))
    if 'allow_methods=["*"]' in api_main:
        findings.append(Finding("cors-method-wildcard", "apps/api/main.py", 0, "CORS methods must be explicit"))
    if 'allow_headers=["*"]' in api_main:
        findings.append(Finding("cors-header-wildcard", "apps/api/main.py", 0, "CORS headers must be explicit"))

    workflow_root = ROOT / ".github" / "workflows"
    for workflow in workflow_root.glob("*.yml"):
        source = workflow.read_text(encoding="utf-8")
        relative = workflow.relative_to(ROOT).as_posix()
        if "pull_request_target:" in source:
            findings.append(Finding("dangerous-workflow-trigger", relative, 0, "pull_request_target is not allowed"))
        if "permissions:\n  contents: read" not in source:
            findings.append(Finding("workflow-permissions", relative, 0, "workflow must declare least-privilege contents: read"))
        for match in re.finditer(r"uses:\s+[^@\s]+@([^\s#]+)", source):
            ref = match.group(1)
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                findings.append(
                    Finding(
                        "unpinned-action",
                        relative,
                        line_number(source, match.start()),
                        "third-party actions must be pinned to a full commit SHA",
                    )
                )
    return findings


def main() -> int:
    findings = [*scan_secrets(tracked_files()), *scan_security_contracts()]
    if findings:
        print("Security governance audit failed:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding.format()}", file=sys.stderr)
        return 1
    print("Security governance audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
