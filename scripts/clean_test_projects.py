"""清理测试项目的脚本

删除所有测试创建的项目，保留用户真实项目。
"""

import json
import shutil
import sys
from pathlib import Path


def clean_test_projects(auto_confirm=False):
    """清理测试项目"""
    projects_root = Path.home() / ".h2ometa" / "projects"
    index_path = Path.home() / ".h2ometa" / "projects.json"

    if not index_path.exists():
        print("项目索引文件不存在")
        return

    # 读取项目索引
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    print(f"当前共有 {len(index)} 个项目")

    # 识别测试项目（名称为"测试项目"或包含"测试"）
    test_projects = []
    for project_id, data in index.items():
        name = data.get("name", "")
        if "测试" in name or name in ["1", "2", "3"]:  # 简单数字名称也视为测试
            test_projects.append((project_id, name))

    if not test_projects:
        print("没有找到测试项目")
        return

    print(f"\n找到 {len(test_projects)} 个测试项目：")
    for project_id, name in test_projects[:10]:  # 只显示前10个
        print(f"  - {name} ({project_id})")
    if len(test_projects) > 10:
        print(f"  ... 还有 {len(test_projects) - 10} 个")

    # 确认删除
    if not auto_confirm:
        response = input("\n是否删除这些项目？(yes/no): ")
        if response.lower() != "yes":
            print("已取消")
            return

    # 删除项目
    deleted_count = 0
    for project_id, name in test_projects:
        try:
            # 删除项目目录
            project_dir = projects_root / project_id
            if project_dir.exists():
                shutil.rmtree(project_dir)

            # 从索引中移除
            if project_id in index:
                del index[project_id]
                deleted_count += 1

        except Exception as e:
            print(f"✗ 删除失败 {project_id}: {e}")

    # 保存更新后的索引
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\n完成！共删除 {deleted_count} 个项目")
    print(f"剩余 {len(index)} 个项目")


if __name__ == "__main__":
    # 如果有命令行参数 --yes，则自动确认
    auto_confirm = "--yes" in sys.argv or "-y" in sys.argv
    clean_test_projects(auto_confirm=auto_confirm)
