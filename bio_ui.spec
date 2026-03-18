# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for H2OMeta UI - Fixed version."""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

# 项目根目录（在某些 PyInstaller 运行上下文下 __file__ 不存在）
project_root = os.path.abspath(os.path.dirname(globals().get("__file__", os.path.join(os.getcwd(), "bio_ui.spec"))))

# 收集 PyQt6 相关数据文件
pyqt6_datas = collect_data_files('PyQt6', include_py_files=False)
pyqt6_webengine_datas = collect_data_files('PyQt6.QtWebEngine', include_py_files=False)
pyqt6_webengine_core_datas = collect_data_files('PyQt6.QtWebEngineCore', include_py_files=False)

# 收集动态库
pyqt6_binaries = collect_dynamic_libs('PyQt6')

# 收集所有子模块
pyqt6_hiddenimports = collect_submodules('PyQt6')
pyqt6_webengine_hiddenimports = collect_submodules('PyQt6.QtWebEngine')
pyqt6_webengine_core_hiddenimports = collect_submodules('PyQt6.QtWebEngineCore')

# 基础数据文件
datas = [
    ('logo.ico', '.'),
    ('config.py', '.'),
    ('requirements.txt', '.'),
    
    # HTML/CSS/JS 文件
    ('ui/pages/detection_page_assets/index_galaxy.html', 'ui/pages/detection_page_assets'),
    ('ui/pages/detection_page_assets/preview_layout.html', 'ui/pages/detection_page_assets'),
    ('ui/pages/detection_page_assets/styles_galaxy.css', 'ui/pages/detection_page_assets'),
    ('ui/pages/detection_page_assets/app_galaxy.js', 'ui/pages/detection_page_assets'),
    ('ui/pages/detection_page_assets/echarts.min.js', 'ui/pages/detection_page_assets'),
    
    ('ui/pages/settings_page_assets/tool_env_table.html', 'ui/pages/settings_page_assets'),
    ('ui/pages/settings_page_assets/tool_env_table.css', 'ui/pages/settings_page_assets'),
    ('ui/pages/settings_page_assets/tool_env_table.js', 'ui/pages/settings_page_assets'),
]

# 添加 PyQt6 数据文件
datas.extend(pyqt6_datas)
datas.extend(pyqt6_webengine_datas)
datas.extend(pyqt6_webengine_core_datas)

# 添加插件目录
if os.path.exists('plugins'):
    datas.append(('plugins', 'plugins'))

# 添加 docs 目录（如果存在）
if os.path.exists('docs'):
    datas.append(('docs', 'docs'))

# 隐藏导入
hiddenimports = [
    # PyQt6 基础
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebChannel',
    'PyQt6.QtWebEngineCore',
    'PyQt6.sip',
    
    # PyQt6 平台插件
    'PyQt6.QtCore.Qt',
    'PyQt6.QtGui.Qt',
    'PyQt6.QtWidgets.Qt',
    
    # 项目模块
    'ui.main_window',
    'ui.qt_bootstrap',
    'ui.page_base',
    'ui.widgets.styles',
    'ui.widgets.ssh_settings_card',
    'ui.widgets.linux_settings_card',
    'ui.widgets.database_paths_card',
    'ui.widgets.ncbi_settings_card',
    'ui.widgets.linux_settings_components',
    'ui.widgets.home_page_components',
    'ui.widgets.detection_page',
    'ui.widgets.stage_status_widget',
    'ui.widgets.input_data_selector',
    'ui.widgets.environment_status_bar',
    'ui.widgets.chart_widget',
    'ui.widgets.export_dialog',
    'ui.widgets.blast_run_card',
    
    # UI 页面
    'ui.pages.project_page',
    'ui.pages.home_page',
    'ui.pages.settings_page',
    'ui.pages.detection_page',
    'ui.pages.log_page',
    
    # 核心模块
    'core',
    'core.environment',
    'core.environment.env_detector',
    'core.environment.env_installer',
    'core.environment.env_batch_checker',
    'core.utils',
    'core.data',
    'core.data.project_manager',
    'core.data.data_registry',
    'core.data.data_importer',
    'core.execution',
    'core.execution.job_queue',
    'core.execution.job_dispatcher',
    'core.execution.tool_engine',
    'core.execution.tool_bridge_service',
    'core.execution.workflow_uploader',
    'core.plugins',
    'core.plugins.plugin_registry',
    'core.service_locator',
    'core.remote',
    'core.remote.ssh_service',
    
    # 第三方库
    'paramiko',
    'paramiko.transport',
    'paramiko.sftp_client',
    'yaml',
    'yaml.loader',
    'yaml.dumper',
    'pyqtdarktheme',
    'jinja2',
    'jinja2.runtime',
    'matplotlib',
    'matplotlib.backends',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_qtagg',
    'matplotlib.pyplot',
    'numpy',
    'numpy.core',
    'numpy.core._dtype_ctypes',
    'PIL',
    'PIL.Image',
    'PIL.ImageQt',
    'PIL.ImageOps',
    'cryptography',
    'bcrypt',
    'pynacl',
]

# 添加 PyQt6 子模块
hiddenimports.extend(pyqt6_hiddenimports)
hiddenimports.extend(pyqt6_webengine_hiddenimports)
hiddenimports.extend(pyqt6_webengine_core_hiddenimports)

# 排除不需要的模块
excludes = [
    'tkinter',
    'matplotlib.tests',
    'numpy.random._examples',
]

a = Analysis(
    ['ui/main.py'],
    pathex=[project_root],
    binaries=pyqt6_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 去除重复项
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='H2OMeta',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 暂时开启控制台以便调试
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.ico',
)
