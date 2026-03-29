from __future__ import annotations

from dataclasses import dataclass
import re

_SPEED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMG]?B/s)", re.IGNORECASE)
_PROGRESS_RE = re.compile(r"(?<!\d)([0-9]{1,3})%(?!\d)")

_RESOLVING_PATTERNS = (
    re.compile(r"solving environment", re.IGNORECASE),
    re.compile(r"collecting package", re.IGNORECASE),
)
_DOWNLOADING_PATTERNS = (
    re.compile(r"downloading", re.IGNORECASE),
    re.compile(r"fetching", re.IGNORECASE),
    re.compile(r"https?://", re.IGNORECASE),
)
_INSTALLING_PATTERNS = (
    re.compile(r"extracting", re.IGNORECASE),
    re.compile(r"preparing", re.IGNORECASE),
    re.compile(r"verifying", re.IGNORECASE),
    re.compile(r"executing transaction", re.IGNORECASE),
    re.compile(r"linking", re.IGNORECASE),
    re.compile(r"post-link", re.IGNORECASE),
    re.compile(r"\brecord\b", re.IGNORECASE),
)

FAILURE_GUIDANCE_TEXT = (
    "[DIAG] 排查建议：\n"
    "- 检查服务器网络连通性与目标仓库可访问性。\n"
    "- 确认 conda 镜像源可用，必要时切换到可用镜像后重试。\n"
    "- 若反复失败，请展开详细日志并定位最后一个报错命令。"
)


@dataclass(frozen=True)
class InstallLogAnalysis:
    normalized_status: str
    phase: str
    phase_text: str
    progress_text: str
    progress_value: int | None
    speed_text: str
    is_progress_indeterminate: bool


def extract_progress_and_speed(text: str) -> tuple[str, str]:
    raw = str(text or "")
    progress = ""
    speed = ""

    progress_matches = list(_PROGRESS_RE.finditer(raw))
    for match in reversed(progress_matches):
        try:
            value = int(match.group(1))
        except Exception:
            continue
        if 0 <= value <= 100:
            progress = f"{value}%"
            break

    speed_matches = list(_SPEED_RE.finditer(raw))
    if speed_matches:
        last = speed_matches[-1]
        speed = f"{last.group(1)}{_normalize_speed_unit(last.group(2))}"

    return progress, speed


def extract_progress_value(text: str) -> int | None:
    progress, _speed = extract_progress_and_speed(text)
    if not progress:
        return None
    try:
        return int(progress.rstrip("%"))
    except ValueError:
        return None


def analyze_install_log(
    status: str,
    *,
    message: str = "",
    log_text: str = "",
    exit_code: str = "",
) -> InstallLogAnalysis:
    normalized_status = str(status or "").strip().upper()
    combined_text = "\n".join(part for part in (str(log_text or ""), str(message or "")) if part)
    progress_text, speed_text = extract_progress_and_speed(combined_text)
    progress_value = extract_progress_value(combined_text)

    if normalized_status == "SUBMITTING":
        return InstallLogAnalysis(
            normalized_status=normalized_status,
            phase="submitting",
            phase_text="正在连接服务器并提交任务",
            progress_text=progress_text,
            progress_value=progress_value,
            speed_text=speed_text,
            is_progress_indeterminate=True,
        )
    if normalized_status == "DONE":
        return InstallLogAnalysis(
            normalized_status=normalized_status,
            phase="success",
            phase_text="安装成功",
            progress_text="100%",
            progress_value=100,
            speed_text="",
            is_progress_indeterminate=False,
        )
    if normalized_status == "FAILED":
        return InstallLogAnalysis(
            normalized_status=normalized_status,
            phase="failed",
            phase_text="安装失败",
            progress_text=progress_text,
            progress_value=progress_value,
            speed_text=speed_text,
            is_progress_indeterminate=False,
        )

    phase = _infer_running_phase(combined_text, progress_text=progress_text, speed_text=speed_text)
    phase_text = {
        "installing": "正在安装软件包",
        "downloading": "正在下载依赖包",
        "resolving": "正在解析依赖",
    }[phase]
    return InstallLogAnalysis(
        normalized_status=normalized_status or "RUNNING",
        phase=phase,
        phase_text=phase_text,
        progress_text=progress_text,
        progress_value=progress_value,
        speed_text=speed_text,
        is_progress_indeterminate=progress_value is None,
    )


def build_failure_guidance(exit_code: str = "") -> str:
    code = str(exit_code or "").strip()
    if not code:
        return FAILURE_GUIDANCE_TEXT
    return f"{FAILURE_GUIDANCE_TEXT}\n- 当前 exit_code: {code}"


def _infer_running_phase(text: str, *, progress_text: str, speed_text: str) -> str:
    raw = str(text or "")
    resolving_index = _last_match_index(raw, _RESOLVING_PATTERNS)
    downloading_index = _last_match_index(raw, _DOWNLOADING_PATTERNS)
    installing_index = _last_match_index(raw, _INSTALLING_PATTERNS)
    progress_index = _last_metric_index(raw) if progress_text or speed_text else -1

    downloading_index = max(downloading_index, progress_index)
    if installing_index >= 0 and installing_index >= max(downloading_index, resolving_index, -1):
        return "installing"
    if downloading_index >= 0 and downloading_index >= max(resolving_index, -1):
        return "downloading"
    return "resolving"


def _last_metric_index(text: str) -> int:
    indexes = [match.end() for match in _PROGRESS_RE.finditer(text)]
    indexes.extend(match.end() for match in _SPEED_RE.finditer(text))
    return max(indexes) if indexes else -1


def _last_match_index(text: str, patterns: tuple[re.Pattern[str], ...]) -> int:
    best = -1
    for pattern in patterns:
        for match in pattern.finditer(text):
            best = max(best, match.end())
    return best


def _normalize_speed_unit(unit: str) -> str:
    raw = str(unit or "").strip()
    if not raw:
        return ""
    if raw.lower() == "b/s":
        return "B/s"
    return f"{raw[:-2].upper()}{raw[-2:].lower()}"
