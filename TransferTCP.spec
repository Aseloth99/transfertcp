# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = []
try:
    d, b, h = collect_all('cryptography')
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtNetwork',
        'src',
        'src.app',
        'src.gui.main_window',
        'src.gui.tray_icon',
        'src.gui.toast',
        'src.gui.settings',
        'src.gui.history_dialog',
        'src.gui.update_dialog',
        'src.gui.trust_dialog',
        'src.gui.message_box',
        'src.gui.chrome_dialog',
        'src.gui.palette',
        'src.gui.about_dialog',
        'src.gui.welcome_dialog',
        'src.gui.manual_device_dialog',
        'src.utils.notify',
        'src.utils.autostart_unix',
        'src.gui.device_list',
        'src.gui.transfer_item',
        'src.gui.icons',
        'src.gui.widgets.stepper_spinbox',
        'src.core.server',
        'src.core.client',
        'src.core.discovery',
        'src.core.transfer',
        'src.core.protocol',
        'src.core.crypto',
        'src.core.netio',
        'cryptography',
        'src.models.device',
        'src.models.transfer',
        'src.models.database',
        'src.utils.config',
        'src.utils.logger',
        'src.utils.helpers',
        'src.utils.paths',
        'src.utils.theme',
        'src.utils.updater',
        'src.utils.update_installer',
        'src.utils.self_update',
        'src.utils.startup',
        'src.utils.crashlog',
        'src.utils.ports',
        'src.utils.locales',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'PySide2', 'PySide6',
        'PyQt6.QtWebEngine', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineQuick', 'PyQt6.QtWebChannel',
        'PyQt6.Qt3DAnimation', 'PyQt6.Qt3DCore', 'PyQt6.Qt3DExtras',
        'PyQt6.Qt3DInput', 'PyQt6.Qt3DLogic', 'PyQt6.Qt3DRender',
        'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtQuick', 'PyQt6.QtQuick3D', 'PyQt6.QtQuickWidgets', 'PyQt6.QtQml',
        'PyQt6.QtBluetooth', 'PyQt6.QtCharts', 'PyQt6.QtDataVisualization',
        'PyQt6.QtLocation', 'PyQt6.QtPositioning', 'PyQt6.QtSensors',
        'PyQt6.QtSerialPort', 'PyQt6.QtSql', 'PyQt6.QtTest', 'PyQt6.QtXml',
        'PyQt6.QtDesigner', 'PyQt6.QtHelp', 'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets',
        'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets', 'PyQt6.QtNfc', 'PyQt6.QtRemoteObjects',
        'PyQt6.QtTextToSpeech', 'PyQt6.QtSpatialAudio', 'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets',
        'PyQt6.QtDBus',
        'tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy', 'PIL', 'cv2', 'torch',
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TransferTCP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icons\\app_icon.ico'],
    version='file_version_info.txt',
)
