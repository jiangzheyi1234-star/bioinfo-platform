# ui/main.py
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录 (bio_ui)
root_dir = os.path.dirname(current_dir)

# 将根目录添加到 Python 搜索路径，防止以后引用 base 或 modules 报错
if root_dir not in sys.path:
    sys.path.append(root_dir)

from PyQt6.QtWidgets import QApplication
# 直接引用同目录下的 main_window
from main_window import MainWindow


def main():
    try:
        app = QApplication(sys.argv)

        # 统一字体
        font = app.font()
        font.setFamily("Segoe UI" if os.name == 'nt' else "Arial")
        app.setFont(font)

        window = MainWindow()
        window.show()

        exit_code = app.exec()
        sys.exit(exit_code)
    except Exception as e:
        import logging
        import traceback
        logging.basicConfig(filename=os.path.join(root_dir, "logs", "startup_error.log"),
                            level=logging.ERROR)
        logging.error("启动失败:\n%s", traceback.format_exc())
        # 同时输出到控制台
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()