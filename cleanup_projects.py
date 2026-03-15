#!/usr/bin/env python3
"""批量删除测试项目脚本"""

import json
import os
import shutil
import sys
from pathlib import Path


def cleanup_all_projects():
    """删除所有项目"""
    projects_root = Path.home() / ".h2ometa" / "projects"
    index_path = Path.home() / ".h2ometa" / "projects.json"

    deleted_count = 0

    # 删除项目目录
    if projects_root.exists():
        for project_dir in projects_root.iterdir():
            if project_dir.is_dir():
                try:
                    shutil.rmtree(project_dir)
                    deleted_count += 1
                    print(f"已删除项目目录: {project_dir.name}")
                except Exception as e:
                    print(f"删除失败 {project_dir.name}: {e}")

    # 清空或删除索引文件
    if index_path.exists():
        try:
            # 写入空对象
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            print(f"已清空项目索引: {index_path}")
        except Exception as e:
            print(f"清空索引失败: {e}")

    print(f"\n清理完成！共删除 {deleted_count} 个项目")


def _guard() -> None:
    expected = "DELETE_ALL_PROJECTS"
    if os.environ.get("H2OMETA_ALLOW_PROJECT_CLEANUP") != "1":
        raise SystemExit(
            "Refusing to run. Set H2OMETA_ALLOW_PROJECT_CLEANUP=1 and pass --confirm DELETE_ALL_PROJECTS."
        )

    if len(sys.argv) != 3 or sys.argv[1] != "--confirm" or sys.argv[2] != expected:
        raise SystemExit(
            "Refusing to run. Usage: cleanup_projects.py --confirm DELETE_ALL_PROJECTS"
        )


if __name__ == "__main__":
    _guard()
    cleanup_all_projects()
