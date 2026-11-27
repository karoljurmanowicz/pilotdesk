"""Punkt startowy PilotDesk.exe.

Łapie każdy błąd startu i zapisuje go do pliku %LOCALAPPDATA%\\PilotDesk\\error.log (Linux/macOS:
~/.local/share/pilotdesk/error.log), zamiast pokazywać okno błędu, które w usłudze lub na serwerze
budującym nie miałby kto zamknąć.

  PilotDesk.exe --selftest PLIK.json   sprawdza, czy wszystkie moduły się ładują (używane przez GitHub Actions)
"""
import json
import os
import sys
import time
import traceback


SYSTEM_ARGS = ("--service", "--agent", "--install-service", "--uninstall-service", "--service-update")


def system_mode():
    return len(sys.argv) > 1 and sys.argv[1] in SYSTEM_ARGS


def log_dir():
    if sys.platform == "win32" and system_mode():
        # usługa i jej agent działają jako SYSTEM – ich dziennik ma być tam, gdzie użytkownik go znajdzie
        d = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "PilotDesk", "logs")
    elif sys.platform == "win32":
        d = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "PilotDesk")
    else:
        d = os.path.join(os.path.expanduser("~"), ".local", "share", "pilotdesk")
    os.makedirs(d, exist_ok=True)
    return d


def write_error(tb):
    try:
        path = os.path.join(log_dir(), "error.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}  {' '.join(sys.argv)}\n{tb}")
        return path
    except Exception:
        return ""


def selftest(out):
    """Ładuje wszystkie moduły i sprawdza najważniejsze możliwości. Zapisuje raport JSON."""
    report = {"ok": True, "modules": {}, "python": sys.version}
    if sys.platform == "win32":  # tak jak w programie: przeciąganie plików ładowane przed bibliotekami dźwięku
        try:
            report["tkdnd_start"] = _tkdnd_check(preload=True)
        except Exception as e:
            report["tkdnd_start"] = f"BŁĄD: {e!r}"
        report["ok"] &= str(report["tkdnd_start"]).startswith("ok")
    mods = ["pd_common", "pd_install", "pd_theme", "pd_ui", "pd_host", "pd_viewer", "pd_media", "pd_clipfiles",
            "pd_winutil", "pd_update", "pd_service", "pd_kvm", "pd_discovery", "pd_net", "pd_log", "pd_diag", "truststore", "certifi", "customtkinter", "mss", "numpy", "PIL.ImageTk", "pynput",
            "pyperclip", "cryptography", "av"]
    if sys.platform == "win32":
        mods += ["pystray", "soundcard", "win32serviceutil", "servicemanager", "win32ts", "win32profile",
                 "win32security", "win32process"]
    for m in mods:
        try:
            __import__(m)
            report["modules"][m] = "ok"
        except Exception as e:
            report["modules"][m] = f"BŁĄD: {e.__class__.__name__}: {e}"
            report["ok"] = False
    try:
        import pd_media
        report["h264_encoder"] = pd_media.h264_encoder_name()
        report["h264_decoder"] = pd_media.h264_decoder_ok()
        report["opus"] = pd_media.opus_ok()
        if report["h264_encoder"]:
            import numpy as np
            enc = pd_media.VideoEncoder(640, 360, 30, 1_000_000)
            data, key = enc.encode(np.zeros((360, 640, 3), dtype=np.uint8))
            dec = pd_media.VideoDecoder()
            img = dec.decode(data)
            report["h264_roundtrip"] = bool(key and img is not None and img.size == (640, 360))
    except Exception as e:
        report["media_error"] = str(e)
        report["ok"] = False
    try:
        import pd_net
        report["tls_context"] = type(pd_net.ssl_context()).__module__
    except Exception as e:
        report["tls_error"] = str(e)
    try:
        import pd_theme
        report["fonts_bundled"] = os.path.isdir(pd_theme.resource("fonts"))
        report["ok"] &= report["fonts_bundled"]
    except Exception as e:
        report["fonts_error"] = str(e)
    if sys.platform == "win32":
        try:
            report["mouse_inject"] = mouse_selftest()
            report["ok"] &= report["mouse_inject"].get("struct_ok", False)
            report["mouse_inject"]["tkdnd_after_audio"] = report["mouse_inject"].pop("tkdnd", None)
        except Exception:
            report["mouse_inject"] = {"error": traceback.format_exc()}
            report["ok"] = False
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return 0 if report["ok"] else 1


def mouse_selftest():
    """Sprawdza wstrzykiwanie myszy (SendInput) na prawdziwym Windows: kliknięcie w okno Tk musi dotrzeć.
    Brak interaktywnego pulpitu na maszynie CI nie psuje testu – zapisujemy tylko wynik."""
    import ctypes
    import tkinter as tk
    import pd_winutil as W
    api = W._mouse_api()
    size = ctypes.sizeof(api["INPUT"])
    r = {"input_size": size, "struct_ok": size == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28),
         "virtual_screen": W.virtual_screen(), "dpi": W.dpi_info()}
    got = []
    root = tk.Tk()
    root.geometry("240x240+120+120")
    root.attributes("-topmost", True)
    c = tk.Canvas(root, width=240, height=240, bg="#202020")
    c.pack()
    c.bind("<ButtonPress>", lambda e: got.append(("down", e.num)))
    c.bind("<ButtonRelease>", lambda e: got.append(("up", e.num)))
    for _ in range(20):
        root.update()
        time.sleep(0.02)
    root.focus_force()
    x = c.winfo_rootx() + 120
    y = c.winfo_rooty() + 120
    r["move"] = W.mouse_move(x, y)
    r["down"] = W.mouse_button(x, y, "left", True)
    r["up"] = W.mouse_button(x, y, "left", False)
    end = time.time() + 1.5
    while time.time() < end and len(got) < 2:
        root.update()
        time.sleep(0.02)
    root.destroy()
    r["tk_events"] = got
    r["click_received"] = ("down", 1) in got and ("up", 1) in got
    try:  # rozdzielczość ekranu (zmiana z okna sesji)
        d = W._disp_api()
        r["devmode_size"] = ctypes.sizeof(d["DEVMODEW"])
        r["struct_ok"] = r["struct_ok"] and r["devmode_size"] == 220
        dev = W.display_device_at(10, 10)
        modes, cur = W.display_modes(dev)
        r["display"] = {"device": dev, "current": cur, "modes": modes[:8]}
    except Exception as e:
        r["display_error"] = repr(e)
        r["struct_ok"] = False
    try:  # po zaimportowaniu soundcard – wątek okna jest już w STA, więc tkdnd musi się dalej ładować
        r["tkdnd"] = _tkdnd_check()
    except Exception as e:
        r["tkdnd"] = f"BŁĄD: {e!r}"
    return r


def _tkdnd_check(preload=False):
    import tkinter as tk
    import pd_files
    root = tk.Tk()
    try:
        pd_files._dnd_loaded["ok"] = None  # nowy interpreter Tcl – ładujemy od nowa
        if preload:
            pd_files.preload(root)
        f = tk.Frame(root)
        f.pack()
        if pd_files.enable_file_drop(f, lambda *a: None):
            return "ok " + str(root.tk.call("package", "present", "tkdnd"))
        return "BŁĄD: " + str(pd_files.TKDND_ERROR.get("msg"))
    finally:
        root.destroy()


def run():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        try:
            sys.exit(selftest(sys.argv[2]))
        except SystemExit:
            raise
        except BaseException:
            with open(sys.argv[2], "w", encoding="utf-8") as f:
                json.dump({"ok": False, "crash": traceback.format_exc()}, f, ensure_ascii=False)
            sys.exit(2)
    try:
        import pd_log
        pd_log.setup()
    except Exception:
        pass
    try:
        import pilotdesk
        pilotdesk.main()
    except SystemExit:
        raise
    except BaseException:
        tb = traceback.format_exc()
        path = write_error(tb)
        gui = not any(a in sys.argv for a in ("--service", "--agent", "--host", "--show-id", "--set-password",
                                              "--install-service", "--uninstall-service", "--service-update"))
        if gui:
            try:
                import tkinter
                from tkinter import messagebox
                r = tkinter.Tk()
                r.withdraw()
                messagebox.showerror("PilotDesk", f"PilotDesk napotkał błąd i musi zostać zamknięty.\n\n"
                                                  f"{tb.strip().splitlines()[-1]}\n\nSzczegóły: {path}")
                r.destroy()
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    run()
