# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onefile）。"""

import os

ROOT = os.path.dirname(os.path.abspath(SPEC))
RESOURCES = os.path.join(ROOT, "resources")

a = Analysis(
    ["src/cloudaccess/__main__.py"],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[
        (os.path.join(RESOURCES, "icon.png"), "resources"),
        (os.path.join(RESOURCES, "icon.ico"), "resources"),
    ],
    hiddenimports=[
        "cloudaccess.providers.aliyun",
        "cloudaccess.providers.tencent",
        "cloudaccess.providers.huawei",
        # six.moves 为动态模块，PyInstaller 静态分析不可见（华为 SDK 内部使用）
        "six",
        "six.moves",
        "six.moves.urllib",
        "six.moves.urllib.parse",
    ],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="cloudaccess",
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(RESOURCES, "icon.ico"),
)
