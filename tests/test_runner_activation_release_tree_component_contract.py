from __future__ import annotations

import pytest

from core.contracts.runner_activation_release_tree import (
    build_runner_activation_release_tree_manifest,
    require_runner_activation_release_tree_component,
)


class _StrSubclass(str):
    def encode(self, *_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("string-subclass methods must not run")

    def split(self, *_args: object, **_kwargs: object) -> list[str]:
        raise AssertionError("string-subclass methods must not run")


@pytest.mark.parametrize(
    "component",
    [
        "A_B",
        ".conda",
        "white space",
        "a:b",
        "x$",
        "~runner+data",
        "a" * 255,
    ],
)
def test_release_tree_component_accepts_the_portable_entry_name_policy(
    component: str,
) -> None:
    assert require_runner_activation_release_tree_component(component) == component


@pytest.mark.parametrize(
    "component",
    [
        None,
        "",
        ".",
        "..",
        "a/b",
        "a\\b",
        " leading",
        "trailing ",
        "a\x1fb",
        "a\x7fb",
        "runnér",
        ".h2ometa-private",
        "a" * 256,
    ],
)
def test_release_tree_component_rejects_nonportable_or_reserved_names(
    component: object,
) -> None:
    with pytest.raises(ValueError, match="release-tree component"):
        require_runner_activation_release_tree_component(component)


def test_release_tree_component_rejects_string_subclasses_before_methods() -> None:
    with pytest.raises(ValueError, match="release-tree component"):
        require_runner_activation_release_tree_component(_StrSubclass("runner"))


def test_release_tree_component_uses_the_caller_error_type() -> None:
    class ComponentError(RuntimeError):
        pass

    with pytest.raises(ComponentError, match="release-tree component"):
        require_runner_activation_release_tree_component(
            "..",
            make_error=ComponentError,
        )


def test_entry_paths_reuse_the_same_component_policy() -> None:
    entry = {
        "contentSha256": "",
        "linkTarget": "",
        "mode": "0555",
        "path": "parent/.h2ometa-private",
        "sizeBytes": 0,
        "type": "directory",
    }

    with pytest.raises(ValueError, match="entry.path"):
        build_runner_activation_release_tree_manifest([entry])


def test_entry_paths_reject_string_subclasses_before_component_methods() -> None:
    entry = {
        "contentSha256": "sha256:" + "a" * 64,
        "linkTarget": "",
        "mode": "0444",
        "path": _StrSubclass("runner"),
        "sizeBytes": 1,
        "type": "file",
    }

    with pytest.raises(ValueError, match="entry.path"):
        build_runner_activation_release_tree_manifest([entry])
