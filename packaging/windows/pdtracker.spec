# PyInstaller recipe for the Windows app. Build from the repository root:
#   pyinstaller packaging/windows/pdtracker.spec
# The result is dist/PriorityDateTracker/, a folder with PriorityDateTracker.exe and everything it needs.

from pathlib import Path

HERE = Path(SPECPATH)
ROOT = HERE.parent.parent

a = Analysis(
    [str(HERE / "launch.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "pdtracker" / "demo" / "*.pdf"), "pdtracker/demo")],
    hiddenimports=["pdtracker.webui", "pdtracker.docketwise", "pdtracker.sharepoint", "msal"],
    excludes=["tkinter", "pytest", "reportlab"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PriorityDateTracker",
    icon=str(HERE / "icon.ico"),
    console=True,      # the window tells staff the dashboard is running; closing it stops the dashboard
)
coll = COLLECT(exe, a.binaries, a.datas, name="PriorityDateTracker")
