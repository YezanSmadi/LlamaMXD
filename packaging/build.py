# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Build the installable app folder: `python packaging/build.py` -> build/dist/LlamaMXD/.

`--installer` then compiles packaging/LlamaMXD.iss (Inno Setup 6) into build/installer/.

Freezes the app with PyInstaller, then adds what the app looks up beside its exe: LICENSE.txt,
licenses/, the manual, and the bundled tools from dependables/ (read only, never changed)."""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(BUILD, "dist")
APP = os.path.join(DIST, "LlamaMXD")
TOOLS = ["ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe", "deno.exe"]   # ffplay.exe is unused


def version():
    """The app's version string, from ui/widgets/panels.py."""
    text = open(os.path.join(ROOT, "ui", "widgets", "panels.py"), encoding="utf-8").read()
    return re.search(r'^VERSION\s*=\s*["\']v?([^"\']+)["\']', text, re.M).group(1)


def numeric_version(ver):
    """`1.0.0-beta.2` as the four numbers Windows version resources want: [1, 0, 0, 0]."""
    nums = [int(n) for n in re.findall(r"\d+", ver.split("-")[0])][:3]
    return nums + [0] * (4 - len(nums))


def make_icon():
    """build/LlamaMXD.ico: a real multi-size icon made from assets/llama.ico, which is a PNG with an
    .ico name (Qt and PyInstaller accept that; Inno Setup does not)."""
    from PIL import Image
    os.makedirs(BUILD, exist_ok=True)
    path = os.path.join(BUILD, "LlamaMXD.ico")
    Image.open(os.path.join(ROOT, "assets", "llama.ico")).convert("RGBA").save(
        path, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return path


def write_version_info():
    """packaging/version_info.txt, the Windows file-properties block of the exe."""
    ver = version()
    nums = numeric_version(ver)
    tup = ", ".join(str(n) for n in nums)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Yezan Smadi'),
      StringStruct('FileDescription', 'LlamaMXD'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'LlamaMXD'),
      StringStruct('LegalCopyright', 'Copyright (C) 2026 Yezan Smadi. GPL-3.0-or-later.'),
      StringStruct('OriginalFilename', 'LlamaMXD.exe'),
      StringStruct('ProductName', 'LlamaMXD'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(os.path.join(HERE, "version_info.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)


def find_iscc():
    """Inno Setup's command-line compiler, or None."""
    candidates = [shutil.which("iscc")]
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            sub = os.path.join("Programs", "Inno Setup 6") if var == "LOCALAPPDATA" else "Inno Setup 6"
            candidates.append(os.path.join(base, sub, "ISCC.exe"))
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def build_installer():
    """Compile the Inno Setup script around the built app folder."""
    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup 6 not found (install it, or put ISCC.exe on PATH)")
    ver = version()
    nums = numeric_version(ver)
    subprocess.run([iscc, f"/DAppVersion={ver}", "/DAppNumeric=" + ".".join(map(str, nums)),
                    os.path.join(HERE, "LlamaMXD.iss")], check=True)
    print(f"installer in {os.path.join(BUILD, 'installer')}")


def main():
    make_icon()
    write_version_info()
    shutil.rmtree(APP, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST,
                    "--workpath", os.path.join(BUILD, "work"), os.path.join(HERE, "LlamaMXD.spec")],
                   cwd=ROOT, check=True)

    shutil.copy2(os.path.join(ROOT, "LICENSE.txt"), APP)
    shutil.copytree(os.path.join(ROOT, "licenses"), os.path.join(APP, "licenses"))
    shutil.copytree(os.path.join(ROOT, "manual"), os.path.join(APP, "manual"),
                    ignore=shutil.ignore_patterns("README.md"))
    tools = os.path.join(APP, "dependables")
    os.makedirs(tools)
    for name in TOOLS:
        src = os.path.join(ROOT, "dependables", name)
        if not os.path.isfile(src):
            sys.exit(f"missing bundled tool: {src}")
        shutil.copy2(src, tools)
    print(f"built {APP} (v{version()})")
    if "--installer" in sys.argv:
        build_installer()


if __name__ == "__main__":
    main()
