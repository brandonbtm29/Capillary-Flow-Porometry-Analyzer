"""Put an app icon where each OS expects one.

- **Windows:** "Capillary Flow Porometry Analyzer" shortcuts on the Desktop and in the Start menu, with the
  app icon and the app's taskbar ID, so a pinned taskbar icon and the running window are one button.
- **macOS:** ``~/Applications/Capillary Flow Porometry Analyzer.app`` (shows in Launchpad and Spotlight;
  drag it to the Dock).
- **Linux:** a ``.desktop`` entry in ``~/.local/share/applications``.

Each one starts this Python environment with ``-m porometry``, so updates from the Update button are
picked up without remaking the icon. Run ``python -m porometry.shortcuts`` or use Settings > Create app icon.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .updater import repo_root

APP_NAME = "Capillary Flow Porometry Analyzer"
APP_ID = "PorometryAnalyzer.App"            # Windows AppUserModelID; gui/app.py sets the same one
BUNDLE_ID = "io.github.brandonbtm29.capillary-flow-porometry-analyzer"
OLD_NAMES = ["Porometry Analyzer"]           # shortcuts from before the rename (v0.1.0)
RESOURCES = Path(__file__).parent / "gui" / "resources"
MARKER = ".shortcut-made"                    # in the venv: the launchers make the icon once, on first start


class ShortcutError(RuntimeError):
    pass


def _gui_python() -> Path:
    """The interpreter to start the app with: pythonw.exe on Windows (no console window)."""
    exe = Path(sys.executable)
    if sys.platform == "win32" and exe.stem.lower() == "python":
        w = exe.with_name("pythonw" + exe.suffix)
        if w.exists():
            return w
    return exe


def _workdir() -> Path:
    return repo_root() or Path.home()


# ------------------------------------------------------------------ Windows
# WScript.Shell can't set the AppUserModelID, so the .lnk is written through IShellLink + IPropertyStore.
_PS_SCRIPT = r'''
param([string]$Target, [string]$WorkDir, [string]$Icon, [string]$AppId,
      [string]$Name, [string]$Description, [string]$OldNames, [string]$Dirs)
$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
namespace Cfpa {
  [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class CShellLink {}
  [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
  interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder f, int cch, IntPtr fd, uint flags);
    void GetIDList(out IntPtr pidl); void SetIDList(IntPtr pidl);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int cch);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int cch);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int cch);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetHotkey(out short k); void SetHotkey(short k);
    void GetShowCmd(out int c); void SetShowCmd(int c);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int cch, out int i);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int i);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint r);
    void Resolve(IntPtr hwnd, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
  }
  [StructLayout(LayoutKind.Sequential, Pack = 4)] public struct PropertyKey { public Guid fmtid; public uint pid; }
  [StructLayout(LayoutKind.Explicit)] public struct PropVariant {
    [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; [FieldOffset(8)] public long pad;
  }
  [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
  interface IPropertyStore {
    void GetCount(out uint c); void GetAt(uint i, out PropertyKey k); void GetValue(ref PropertyKey k, out PropVariant v);
    void SetValue(ref PropertyKey k, ref PropVariant v); void Commit();
  }
  public static class Lnk {
    public static void Write(string lnk, string target, string args, string dir, string icon, string desc, string appId) {
      var link = (IShellLinkW)new CShellLink();
      link.SetPath(target); link.SetArguments(args); link.SetWorkingDirectory(dir);
      link.SetIconLocation(icon, 0); link.SetDescription(desc);
      var key = new PropertyKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
      var v = new PropVariant { vt = 31, p = Marshal.StringToCoTaskMemUni(appId) };
      var store = (IPropertyStore)link;
      try { store.SetValue(ref key, ref v); store.Commit(); } finally { Marshal.FreeCoTaskMem(v.p); }
      ((IPersistFile)link).Save(lnk, true);
    }
  }
}
"@
$targets = if ($Dirs) { $Dirs -split ";" } else { @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs")) }
foreach ($dir in $targets) {
  foreach ($old in ($OldNames -split ";")) {
    $o = Join-Path $dir "$old.lnk"
    if ($old -and (Test-Path $o)) { Remove-Item $o; Write-Output "removed`t$o" }
  }
  $t = Join-Path $dir "$Name.lnk"
  [Cfpa.Lnk]::Write($t, $Target, "-m porometry", $WorkDir, $Icon, $Description, $AppId)
  Write-Output "created`t$t"
}
'''


def _windows(dirs: list[Path] | None = None) -> list[Path]:
    """Desktop + Start menu shortcuts (or into `dirs`, for tests)."""
    with tempfile.TemporaryDirectory() as tmp:
        ps1 = Path(tmp) / "make_shortcut.ps1"
        ps1.write_text(_PS_SCRIPT, encoding="utf-8-sig")  # BOM: Windows PowerShell 5 reads it as UTF-8
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
               "-Target", str(_gui_python()), "-WorkDir", str(_workdir()),
               "-Icon", str(RESOURCES / "porometry.ico"), "-AppId", APP_ID, "-Name", APP_NAME,
               "-Description", "Capillary flow porometry analysis (CapWin .CFT files)",
               "-OldNames", ";".join(OLD_NAMES), "-Dirs", ";".join(str(d) for d in dirs or [])]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise ShortcutError(f"PowerShell could not create the shortcut:\n{(r.stderr or r.stdout).strip()[-1500:]}")
    return [Path(line.split("\t", 1)[1]) for line in r.stdout.splitlines() if line.startswith("created\t")]


# ------------------------------------------------------------------ macOS
def mac_bundle(apps_dir: Path | None = None, python: Path | None = None, workdir: Path | None = None) -> Path:
    """Write ``<apps_dir>/Capillary Flow Porometry Analyzer.app``. Works on any OS (tests build it on Linux)."""
    apps = Path(apps_dir or Path.home() / "Applications")
    app = apps / f"{APP_NAME}.app"
    if app.exists():
        info = app / "Contents" / "Info.plist"
        try:
            ours = plistlib.loads(info.read_bytes()).get("CFBundleIdentifier") == BUNDLE_ID
        except (OSError, plistlib.InvalidFileException):
            ours = False
        if not ours:
            raise ShortcutError(f"{app} exists and wasn't made by this app; move it away first.")
        shutil.rmtree(app)
    macos, res = app / "Contents" / "MacOS", app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    res.mkdir()
    exe = macos / "launcher"
    py, wd = Path(python or _gui_python()), Path(workdir or _workdir())
    exe.write_text("#!/bin/bash\n"
                   f"# Made by {APP_NAME} {__version__} (python -m porometry.shortcuts). Starts the app from:\n"
                   f'cd "{wd}" 2>/dev/null || cd "$HOME"\n'
                   f'exec "{py}" -m porometry "$@"\n', encoding="utf-8")
    exe.chmod(0o755)
    from PIL import Image  # comes with matplotlib
    with Image.open(RESOURCES / "porometry_1024.png") as im:
        im.convert("RGBA").save(res / "porometry.icns", format="ICNS")
    plist = {
        "CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME, "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "launcher", "CFBundleIconFile": "porometry.icns", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": "10.15", "NSHighResolutionCapable": True,
    }
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
    os.utime(app)  # nudge Finder to pick up the icon
    return app


# ------------------------------------------------------------------ Linux
def _linux() -> list[Path]:
    d = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "capillary-flow-porometry-analyzer.desktop"
    f.write_text("[Desktop Entry]\nType=Application\n"
                 f"Name={APP_NAME}\nComment=Capillary flow porometry analysis (CapWin .CFT files)\n"
                 f'Exec="{_gui_python()}" -m porometry %F\nPath={_workdir()}\n'
                 f"Icon={RESOURCES / 'porometry_256.png'}\nTerminal=false\nCategories=Science;Education;\n",
                 encoding="utf-8")
    f.chmod(0o755)
    return [f]


# ------------------------------------------------------------------ entry points
def create() -> list[Path]:
    """Create (or refresh) the app icon for this computer. Returns what was created."""
    if sys.platform == "win32":
        made = _windows()
    elif sys.platform == "darwin":
        made = [mac_bundle()]
    else:
        made = _linux()
    try:
        (Path(sys.prefix) / MARKER).write_text(__version__)
    except OSError:
        pass
    return made


def where() -> str:
    """Where the icon goes on this OS, in plain words."""
    if sys.platform == "win32":
        return "on the Desktop and in the Start menu (right-click it there to pin it to the taskbar)"
    if sys.platform == "darwin":
        return "in Applications in your home folder (drag it to the Dock to keep it there)"
    return "in your applications menu"


def main() -> int:
    try:
        made = create()
    except Exception as exc:
        print(f"Could not create the app icon: {exc}", file=sys.stderr)
        return 1
    for p in made:
        print(f"Created {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
