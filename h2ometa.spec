# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for H2OMeta metagenomics analysis platform."""

import os

block_cipher = None
PROJECT_ROOT = os.path.abspath('.')

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'ui', 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, 'plugins'), 'plugins'),
        (os.path.join(PROJECT_ROOT, 'ui', 'pages', 'detection_page_assets'),
         os.path.join('ui', 'pages', 'detection_page_assets')),
        (os.path.join(PROJECT_ROOT, 'ui', 'pages', 'settings_page_assets'),
         os.path.join('ui', 'pages', 'settings_page_assets')),
        (os.path.join(PROJECT_ROOT, 'logo.ico'), '.'),
    ],
    hiddenimports=[
        # paramiko + cryptography
        'paramiko', 'paramiko.transport', 'paramiko.sftp_client',
        'paramiko.rsakey', 'paramiko.ecdsakey', 'paramiko.ed25519key',
        'paramiko.ssh_exception',
        'cryptography.hazmat.primitives.ciphers',
        'cryptography.hazmat.primitives.kdf',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        'cryptography.hazmat.primitives.asymmetric.ec',
        'cryptography.hazmat.primitives.asymmetric.rsa',
        'cryptography.hazmat.primitives.asymmetric.padding',
        'cryptography.hazmat.backends.openssl',
        'bcrypt', 'nacl', 'nacl.bindings',
        # PyQt6 / QtWebEngine
        'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebChannel', 'PyQt6.sip',
        # Jinja2
        'jinja2', 'jinja2.ext', 'markupsafe',
        # matplotlib
        'matplotlib.backends.backend_qtagg',
        # YAML
        'yaml',
        # app modules
        'config',
        'core', 'core.utils', 'core.service_locator',
        'core.plugins.plugin_registry', 'core.plugins.task_manager',
        'core.execution.command_builder', 'core.execution.tool_engine',
        'core.execution.job_dispatcher', 'core.execution.job_queue',
        'core.execution.job_monitor', 'core.execution.retry_manager',
        'core.execution.tool_bridge_service',
        'core.data.data_registry', 'core.data.project_manager',
        'core.data.sample_service', 'core.data.data_importer',
        'core.data.execution_cleaner',
        'core.remote.ssh_service', 'core.remote.ssh_connector',
        'core.remote.ssh_reconnector', 'core.remote.storage_manager',
        'core.environment.env_detector', 'core.environment.env_installer',
        'core.environment.env_batch_checker', 'core.environment.container_detector',
        'core.pipeline.pipeline_runner', 'core.pipeline.report_generator',
        'core.pipeline.detection_merger', 'core.pipeline.blast_result_parser',
        'core.pipeline.chart_data_parser',
        'ui.main_window',
        'ui.pages.detection_page_web', 'ui.pages.settings_page',
        'ui.pages.home_page', 'ui.pages.log_page', 'ui.pages.project_page',
        'ui.widgets.linux_settings_card', 'ui.widgets.ssh_settings_card',
        'ui.widgets.chart_widget', 'ui.widgets.styles',
        'ui.widgets.environment_status_bar',
        'ui.qt_bootstrap',
        'ui.controllers.home_page_controller',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(PROJECT_ROOT, 'hooks', 'rthook_qtwebengine.py')],
    excludes=[
        'pytest', 'pytest_cache', '_pytest', 'pluggy', 'iniconfig',
        'conftest', 'tkinter', '_tkinter', 'doctest',
        'pdb', 'pydoc', 'pyqtdarktheme',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    # Keep modules as loose files in the bundle to reduce startup unpack/decompress overhead.
    noarchive=True,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    # Onedir mode: binaries collected separately (faster startup than onefile extraction).
    exclude_binaries=True,
    name='H2OMeta',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, 'logo.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='H2OMeta',
)
