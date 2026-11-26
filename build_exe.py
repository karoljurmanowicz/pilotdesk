"""Buduje PilotDesk.exe (Windows) przy pomocy PyInstallera.

    python build_exe.py

Wynik: dist/PilotDesk.exe – jeden plik, który jest jednocześnie instalatorem i programem.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    from pd_common import VERSION
    import pd_theme
    os.makedirs(os.path.join(HERE, "build"), exist_ok=True)
    ico = pd_theme.save_ico(os.path.join(HERE, "build", "pilotdesk.ico"))
    v = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    ver_file = os.path.join(HERE, "build", "version.txt")
    with open(ver_file, "w", encoding="utf-8") as f:
        f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('041504B0', [
      StringStruct('CompanyName', 'PilotDesk'),
      StringStruct('FileDescription', 'PilotDesk - zdalny pulpit'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'PilotDesk'),
      StringStruct('OriginalFilename', 'PilotDesk.exe'),
      StringStruct('ProductName', 'PilotDesk'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [0x0415, 1200])])])
""")
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "PilotDesk", "--icon", ico, "--version-file", ver_file,
        "--collect-data", "customtkinter", "--collect-data", "soundcard", "--collect-submodules", "av",
        "--add-data", os.path.join(HERE, "fonts") + os.pathsep + "fonts",
        "--add-data", os.path.join(HERE, "CHANGELOG.md") + os.pathsep + ".",
        "--hidden-import", "pynput.keyboard._win32", "--hidden-import", "pynput.mouse._win32",
        "--hidden-import", "pystray._win32", "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "win32timezone", "--hidden-import", "servicemanager",
        "--hidden-import", "win32serviceutil", "--hidden-import", "win32ts", "--hidden-import", "win32profile",
        "--exclude-module", "matplotlib", "--exclude-module", "scipy", "--exclude-module", "pandas",
        "--hidden-import", "pilotdesk",
        os.path.join(HERE, "launcher.py"),
    ]
    print(" ".join(args))
    subprocess.check_call(args, cwd=HERE)
    import hashlib
    exe = os.path.join(HERE, "dist", "PilotDesk.exe" if sys.platform == "win32" else "PilotDesk")
    with open(exe, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(exe + ".sha256", "w") as f:
        f.write(digest + "  PilotDesk.exe\n")
    print("\nGotowe:", exe, "\nSHA-256:", digest)


if __name__ == "__main__":
    main()
