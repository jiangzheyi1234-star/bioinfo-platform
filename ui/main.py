# ui/main.py
import sys
import os

# 获取当前文件所在目录 (ui)
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录 (bio_ui)
root_dir = os.path.dirname(current_dir)

# 将根目录添加到 Python 搜索路径，防止以后引用 base 或 modules 报错
if root_dir not in sys.path:
    sys.path.append(root_dir)

from PyQt6.QtWidgets import QApplication
# 修正导入语句
try:
    from main_window import MainWindow
except ImportError:
    from .main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    # 统一字体
    font = app.font()
    font.setFamily("Segoe UI" if os.name == 'nt' else "Arial")
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()