"""PilotDesk – instalacja: kopiowanie programu, skróty (pulpit, menu Start), autostart, odinstalowanie,
pojedyncza instancja programu."""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

APP = "PilotDesk"
INSTANCE_PORT = 47801
CREATE_NO_WINDOW = 0x08000000
DETACHED = 0x00000008


def is_windows():
    return sys.platform == "win32"


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def install_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", APP)


def installed_exe():
    return os.path.join(install_dir(), f"{APP}.exe")


def is_installed():
    return is_windows() and os.path.exists(installed_exe())


def running_installed():
    if not (is_windows() and is_frozen() and is_installed()):
        return False
    try:
        return os.path.samefile(sys.executable, installed_exe())
    except OSError:
        return False


def should_offer_install():
    return is_windows() and is_frozen() and not running_installed()


def launch_command(exe=None):
    """Polecenie uruchamiające program (exe albo pythonw + skrypt)."""
    if exe:
        return [exe]
    if is_frozen():
        return [sys.executable]
    py = sys.executable
    if is_windows():
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.exists(pyw):
            py = pyw
    return [py, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pilotdesk.py"))]


def _q(s):
    return '"' + s + '"'


def _ps(script):
    """Uruchamia skrypt PowerShell bez okna konsoli."""
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=60)


def _psq(s):
    return "'" + s.replace("'", "''") + "'"


def special_folder(name):
    if not is_windows():
        return os.path.expanduser("~/Desktop")
    r = _ps(f"[Environment]::GetFolderPath('{name}')")
    p = r.stdout.strip()
    if not p:
        p = os.path.join(os.path.expanduser("~"), "Desktop" if name == "Desktop" else "")
    return p


def create_shortcut_win(lnk_path, cmd, icon):
    target, args = cmd[0], " ".join(_q(a) if " " in a else a for a in cmd[1:])
    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_psq(lnk_path)});"
              f"$s.TargetPath={_psq(target)};$s.Arguments={_psq(args)};"
              f"$s.WorkingDirectory={_psq(os.path.dirname(target))};"
              f"$s.IconLocation={_psq(icon + ',0')};$s.Description='PilotDesk - zdalny pulpit';$s.Save()")
    r = _ps(script)
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or "nie udało się utworzyć skrótu")


def create_desktop_shortcut(exe=None):
    """Skrót na pulpicie (Windows: .lnk, Linux: .desktop)."""
    from pd_theme import icon_file, save_ico
    cmd = launch_command(exe)
    if is_windows():
        if exe:
            ico = os.path.join(os.path.dirname(exe), "pilotdesk.ico")
            save_ico(ico)
        else:
            ico = icon_file()
        path = os.path.join(special_folder("Desktop"), f"{APP}.lnk")
        create_shortcut_win(path, cmd, ico)
        return path
    desk = _desktop_entry(cmd)
    out = []
    for d in (os.path.expanduser("~/Desktop"), os.path.expanduser("~/Pulpit"),
              os.path.expanduser("~/.local/share/applications")):
        if os.path.isdir(d) or d.endswith("applications"):
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "pilotdesk.desktop")
            with open(p, "w", encoding="utf-8") as f:
                f.write(desk)
            os.chmod(p, 0o755)
            out.append(p)
    return out[0] if out else ""


def _desktop_entry(cmd, extra=""):
    from pd_theme import icon_file
    exe = " ".join(f'"{c}"' for c in cmd)
    return (f"[Desktop Entry]\nType=Application\nName=PilotDesk\nComment=Zdalny pulpit\nExec={exe}{extra}\n"
            f"Icon={icon_file()}\nTerminal=false\nCategories=Network;RemoteAccess;\n")


# --------------------------------------------------------------------------- autostart

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PilotDesk"


def _autostart_file():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/LaunchAgents/pl.pilotdesk.agent.plist")
    return os.path.expanduser("~/.config/autostart/pilotdesk.desktop")


def autostart_enabled():
    if is_windows():
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, APP)
                return True
        except OSError:
            return False
    return os.path.exists(_autostart_file())


def set_autostart(enabled, exe=None):
    cmd = launch_command(exe) + ["--minimized"]
    if is_windows():
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if enabled:
                winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, " ".join(_q(c) if not c.startswith("--") else c for c in cmd))
            else:
                try:
                    winreg.DeleteValue(k, APP)
                except OSError:
                    pass
        old = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup",
                           "PilotDesk.vbs")  # stara wersja 1.0
        if os.path.exists(old):
            os.remove(old)
        return
    path = _autostart_file()
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if sys.platform == "darwin":
        args = "".join(f"<string>{c}</string>" for c in cmd)
        content = ('<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
                   '<key>Label</key><string>pl.pilotdesk.agent</string>'
                   f'<key>ProgramArguments</key><array>{args}</array><key>RunAtLoad</key><true/></dict></plist>\n')
    else:
        content = _desktop_entry(cmd[:-1], " --minimized") + "X-GNOME-Autostart-enabled=true\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# --------------------------------------------------------------------------- instalacja Windows

def install(desktop=True, start_menu=True, autostart=True, version="", log=lambda m: None):
    """Kopiuje PilotDesk.exe do %LOCALAPPDATA%\\Programs\\PilotDesk i tworzy skróty."""
    from pd_theme import save_ico
    src = sys.executable
    dst_dir = install_dir()
    dst = installed_exe()
    os.makedirs(dst_dir, exist_ok=True)
    # zamknij działającą starą wersję
    send_to_instance("quit")
    for _ in range(20):
        try:
            if os.path.exists(dst):
                os.replace(dst, dst + ".old")
            break
        except OSError:
            time.sleep(0.3)
    log("Kopiowanie programu…")
    shutil.copy2(src, dst)
    try:
        os.remove(dst + ".old")
    except OSError:
        pass
    ico = os.path.join(dst_dir, "pilotdesk.ico")
    save_ico(ico)
    cmd = [dst]
    if desktop:
        log("Skrót na pulpicie…")
        create_shortcut_win(os.path.join(special_folder("Desktop"), f"{APP}.lnk"), cmd, ico)
    if start_menu:
        log("Menu Start…")
        create_shortcut_win(os.path.join(special_folder("Programs"), f"{APP}.lnk"), cmd, ico)
    set_autostart(autostart, exe=dst)
    log("Rejestracja w „Aplikacje i funkcje”…")
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in (("DisplayName", "PilotDesk"), ("DisplayVersion", version), ("Publisher", "PilotDesk"),
                          ("DisplayIcon", ico), ("InstallLocation", dst_dir),
                          ("UninstallString", f'"{dst}" --uninstall')):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, int(os.path.getsize(dst) / 1024))
    return dst


def uninstall(remove_settings=False):
    import winreg
    send_to_instance("quit")
    for folder in ("Desktop", "Programs"):
        p = os.path.join(special_folder(folder), f"{APP}.lnk")
        if os.path.exists(p):
            os.remove(p)
    set_autostart(False)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    if remove_settings:
        from pd_common import config_path
        try:
            os.remove(config_path())
        except OSError:
            pass
    # folderu z działającym exe nie da się usunąć od razu – robi to cmd po zakończeniu programu
    subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 3 > nul & rmdir /s /q "{install_dir()}"',
                     creationflags=CREATE_NO_WINDOW | DETACHED, close_fds=True)


def launch_detached(cmd):
    kw = {"close_fds": True}
    if is_windows():
        kw["creationflags"] = DETACHED
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


# --------------------------------------------------------------------------- jedna instancja

def send_to_instance(cmd):
    try:
        with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=1) as s:
            s.sendall(cmd.encode() + b"\n")
            if cmd == "quit":
                time.sleep(1.2)
            return True
    except OSError:
        return False


class SingleInstance:
    """Nasłuch na localhost: drugie uruchomienie programu pokazuje okno pierwszego."""

    def __init__(self, on_command):
        self.on_command = on_command
        self.sock = None

    def acquire(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if is_windows() and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind(("127.0.0.1", INSTANCE_PORT))
            s.listen(4)
        except OSError:
            s.close()
            return False
        self.sock = s
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def _loop(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            try:
                c.settimeout(2)
                data = c.recv(64).decode(errors="ignore").strip()
                if data in ("show", "quit"):
                    self.on_command(data)
            except OSError:
                pass
            finally:
                c.close()


def shortcut_exists(folder="Desktop"):
    if not is_windows():
        return False
    try:
        return os.path.exists(os.path.join(special_folder(folder), f"{APP}.lnk"))
    except Exception:
        return False


def apply_update_from_here(version):
    """Uruchamiane jako `nowy.exe --apply-update`: instaluje się w miejsce starej wersji i ją uruchamia."""
    exe = install(desktop=shortcut_exists("Desktop"), start_menu=shortcut_exists("Programs"),
                  autostart=autostart_enabled(), version=version)
    launch_detached([exe])
