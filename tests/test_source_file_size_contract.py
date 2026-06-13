from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("apps", "core", "tests")
MAX_HAND_WRITTEN_SOURCE_LINES = 800
MAX_ROUTE_STRUCTURE_CONTRACT_LINES = 760
MAX_TEST_SOURCE_LINES = MAX_HAND_WRITTEN_SOURCE_LINES


def _python_source_files() -> list[Path]:
    return [
        path
        for source_root in SOURCE_ROOTS
        for path in (REPOSITORY_ROOT / source_root).rglob("*.py")
        if ".venv-win" not in path.parts
    ]


def test_hand_written_python_source_files_stay_under_line_limit() -> None:
    oversized = {
        path.relative_to(REPOSITORY_ROOT).as_posix(): len(path.read_text(encoding="utf-8").splitlines())
        for path in _python_source_files()
        if len(path.read_text(encoding="utf-8").splitlines()) > MAX_HAND_WRITTEN_SOURCE_LINES
    }

    assert oversized == {}


def test_route_structure_contract_modules_are_split_before_source_limit() -> None:
    oversized = {
        path.relative_to(REPOSITORY_ROOT).as_posix(): len(path.read_text(encoding="utf-8").splitlines())
        for path in (REPOSITORY_ROOT / "tests").glob("*route_structure.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > MAX_ROUTE_STRUCTURE_CONTRACT_LINES
    }

    assert oversized == {}


def test_test_modules_are_split_before_source_limit() -> None:
    oversized = {
        path.relative_to(REPOSITORY_ROOT).as_posix(): len(path.read_text(encoding="utf-8").splitlines())
        for path in (REPOSITORY_ROOT / "tests").glob("test_*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > MAX_TEST_SOURCE_LINES
    }

    assert oversized == {}
