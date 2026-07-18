from __future__ import annotations

import platform
import sys

from setuptools import Extension, setup


if sys.platform != "linux" or platform.machine().lower() != "x86_64":
    raise RuntimeError(
        "activation release directory owner proof builds require Linux x86_64"
    )

extension = Extension(
    "remote_runner._activation_release_dir_owner",
    sources=["src/activation_release_dir_owner.c"],
    py_limited_api=True,
    extra_compile_args=[
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wpedantic",
        "-fvisibility=hidden",
        "-fstack-protector-strong",
    ],
    extra_link_args=["-Wl,-z,relro", "-Wl,-z,now"],
)

setup(
    ext_modules=[extension],
    options={"bdist_wheel": {"py_limited_api": "cp312"}},
)
