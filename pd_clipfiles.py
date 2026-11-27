"""PilotDesk – pliki w schowku (Ctrl+C na pliku w Eksploratorze -> Ctrl+V na drugim komputerze).

Windows: format CF_HDROP (lista ścieżek) + „Preferred DropEffect” = kopiuj.
Linux: text/uri-list przez xclip.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, unquote, urlparse

CF_HDROP = 15


def clip_temp_root():
    d = os.path.join(tempfile.gettempdir(), "PilotDesk-schowek")
    os.makedirs(d, exist_ok=True)
    return d


def cleanup_old(max_age=24 * 3600):
    root = clip_temp_root()
    now = time.time()
    for n in os.listdir(root):
        p = os.path.join(root, n)
        try:
            if now - os.path.getmtime(p) > max_age:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _u = ctypes.WinDLL("user32", use_last_error=True)
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    _s = ctypes.WinDLL("shell32", use_last_error=True)
    _u.OpenClipboard.argtypes = [wintypes.HWND]
    _u.OpenClipboard.restype = wintypes.BOOL
    _u.CloseClipboard.restype = wintypes.BOOL
    _u.EmptyClipboard.restype = wintypes.BOOL
    _u.GetClipboardData.argtypes = [wintypes.UINT]
    _u.GetClipboardData.restype = wintypes.HANDLE
    _u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _u.SetClipboardData.restype = wintypes.HANDLE
    _u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _u.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    _u.RegisterClipboardFormatW.restype = wintypes.UINT
    _u.GetClipboardSequenceNumber.restype = wintypes.DWORD
    _k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _k.GlobalAlloc.restype = wintypes.HGLOBAL
    _k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _k.GlobalLock.restype = ctypes.c_void_p
    _k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _k.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _s.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    _s.DragQueryFileW.restype = wintypes.UINT

    _u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
    _u.CreateWindowExW.restype = wintypes.HWND
    import threading as _th
    _tl = _th.local()

    def _owner():
        """Niewidoczne okno-właściciel schowka (osobne dla każdego wątku). Bez niego Windows: OpenClipboard(NULL)
        + EmptyClipboard ustawia „brak właściciela” i SetClipboardData po cichu się nie udaje – pliki skopiowane
        z drugiego komputera nigdy nie trafiały do schowka."""
        h = getattr(_tl, "hwnd", None)
        if not h:
            h = _u.CreateWindowExW(0, "STATIC", "PilotDesk-schowek", 0, 0, 0, 0, 0, None, None, None, None)
            _tl.hwnd = h
        return h

    def _open():
        owner = _owner()
        for _ in range(50):
            if _u.OpenClipboard(owner):
                return True
            time.sleep(0.02)
        return False

    def sequence():
        return int(_u.GetClipboardSequenceNumber())

    def get_files():
        if not _u.IsClipboardFormatAvailable(CF_HDROP):
            return None
        if not _open():
            return None
        try:
            h = _u.GetClipboardData(CF_HDROP)
            if not h:
                return None
            n = _s.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
            out = []
            for i in range(n):
                ln = _s.DragQueryFileW(h, i, None, 0)
                buf = ctypes.create_unicode_buffer(ln + 1)
                _s.DragQueryFileW(h, i, buf, ln + 1)
                out.append(buf.value)
            return out or None
        finally:
            _u.CloseClipboard()

    def _global(data):
        h = _k.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
        p = _k.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        _k.GlobalUnlock(h)
        return h

    def set_files(paths):
        import struct
        files = ("\0".join(paths) + "\0\0").encode("utf-16-le")
        dropfiles = struct.pack("<IiiII", 20, 0, 0, 0, 1) + files  # pFiles, pt.x, pt.y, fNC, fWide
        effect = struct.pack("<I", 1)  # DROPEFFECT_COPY
        if not _open():
            return False
        try:
            _u.EmptyClipboard()
            if not _u.SetClipboardData(CF_HDROP, _global(dropfiles)):
                return False
            fmt = _u.RegisterClipboardFormatW("Preferred DropEffect")
            _u.SetClipboardData(fmt, _global(effect))
            return True
        finally:
            _u.CloseClipboard()

    def available():
        return True

else:
    def _xclip(*args, data=None):
        return subprocess.run(["xclip", "-selection", "clipboard", *args], input=data, capture_output=True,
                              timeout=3)

    def available():
        return sys.platform.startswith("linux") and shutil.which("xclip") is not None

    _seq = [0, None]

    def sequence():
        """Na Linuksie nie ma licznika zmian – sprawdzamy listę dostępnych formatów i zawartość."""
        try:
            r = _xclip("-t", "TARGETS", "-o")
            if b"text/uri-list" not in r.stdout:
                return 0
            return hash(_xclip("-t", "text/uri-list", "-o").stdout)
        except Exception:
            return 0

    def get_files():
        if not available():
            return None
        try:
            r = _xclip("-t", "TARGETS", "-o")
            if b"text/uri-list" not in r.stdout:
                return None
            out = []
            for line in _xclip("-t", "text/uri-list", "-o").stdout.decode("utf-8", "replace").splitlines():
                line = line.strip()
                if line.startswith("file://"):
                    out.append(unquote(urlparse(line).path))
            return [p for p in out if os.path.exists(p)] or None
        except Exception:
            return None

    def set_files(paths):
        if not available():
            return False
        data = "\r\n".join("file://" + quote(os.path.abspath(p)) for p in paths) + "\r\n"
        # xclip zostaje w tle i „trzyma” schowek, dopóki ktoś inny go nie zmieni
        subprocess.Popen(["xclip", "-selection", "clipboard", "-t", "text/uri-list"], stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).communicate(data.encode(), timeout=3)
        return True


def total_size(paths):
    n = 0
    for p in paths:
        if os.path.isdir(p):
            for root, _d, files in os.walk(p):
                for f in files:
                    try:
                        n += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        else:
            try:
                n += os.path.getsize(p)
            except OSError:
                pass
    return n


class ClipboardSync:
    """Synchronizacja schowka (tekst + pliki) w osobnym wątku. Używana po obu stronach połączenia.

    send_json / send_file_fn – wysyłanie przez zaszyfrowany kanał (bezpieczne wątkowo),
    enabled() – czy synchronizacja jest włączona, notice(tekst) – komunikat dla użytkownika,
    progress(id, nazwa, zrobione, razem, status) – postęp wysyłania plików ze schowka.
    """

    MAX_BYTES = 4 * 1024 ** 3

    def __init__(self, send_json, send_file_fn, enabled=lambda: True, notice=None, progress=None,
                 files_enabled=True, pre_op=None):
        import queue
        import threading
        self.send_json = send_json
        self.send_file_fn = send_file_fn
        self.enabled = enabled
        self.notice = notice or (lambda t: None)
        self.progress = progress
        self.files_enabled = files_enabled and available()
        self.pre_op = pre_op
        self.q = queue.Queue()
        self.running = False
        self.text_last = None
        self.files_applied = None
        self.cancel = None
        self._threading = threading

    def start(self):
        self.running = True
        self._threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False
        if self.cancel:
            self.cancel.set()

    # --- zdarzenia z drugiej strony (wołane z wątku odbiorczego)
    def remote_text(self, text):
        self.q.put(("text", text))

    @staticmethod
    def clip_dir(cid):
        safe = "".join(c for c in str(cid) if c.isalnum())[:40] or "x"
        return os.path.join(clip_temp_root(), safe)

    def remote_files_end(self, msg):
        base = self.clip_dir(msg.get("id"))
        paths = [os.path.join(base, os.path.basename(n)) for n in msg.get("names", [])]
        paths = [p for p in paths if os.path.exists(p)]
        if paths:
            self.q.put(("files", paths))

    # --- wątek
    def _paste(self):
        import pyperclip
        return pyperclip.paste()

    def _copy(self, t):
        import pyperclip
        pyperclip.copy(t)

    def _run(self):
        try:
            cleanup_old()
        except Exception:
            pass
        try:
            self.text_last = self._paste()
        except Exception:
            self.text_last = None
        seq = sequence() if self.files_enabled else None
        while self.running:
            if self.pre_op:
                try:
                    self.pre_op()
                except Exception:
                    pass
            applied = False
            while not self.q.empty():
                kind, val = self.q.get()
                try:
                    if kind == "text":
                        self.text_last = val
                        self._copy(val)
                    else:
                        if set_files(val):
                            self.files_applied = tuple(val)
                            self.notice(f"Pliki ze schowka gotowe ({len(val)}) – wklej je Ctrl+V")
                    applied = True
                except Exception:
                    pass
            if applied and self.files_enabled:
                time.sleep(0.15)
                seq = sequence()
            time.sleep(0.4)
            if not self.enabled():
                continue
            if self.files_enabled:
                try:
                    s = sequence()
                    if s != seq:
                        seq = s
                        files = get_files()
                        if files and tuple(files) != self.files_applied:
                            self.files_applied = tuple(files)
                            self._send_files(files)
                            continue
                except Exception:
                    pass
            try:
                txt = self._paste()
            except Exception:
                continue
            if txt and txt != self.text_last and len(txt) < 20_000_000:
                self.text_last = txt
                self.send_json({"t": "clipboard", "text": txt})

    def _send_files(self, files):
        import secrets
        if self.cancel:
            self.cancel.set()
        total = total_size(files)
        if total > self.MAX_BYTES:
            self.notice("Skopiowane pliki są za duże dla schowka – użyj menedżera plików.")
            return
        cancel = self._threading.Event()
        self.cancel = cancel
        cid = secrets.token_hex(8)
        names = [os.path.basename(p.rstrip("\\/")) for p in files]

        def work():
            from pd_common import iter_path_files
            try:
                self.send_json({"t": "clip_files_begin", "id": cid, "names": names, "total": total})
                for p in files:
                    for full, rel in iter_path_files(p):
                        if cancel.is_set() or not self.running:
                            return
                        self.send_file_fn(full, rel, {"clip": cid}, cancel)
                if not cancel.is_set():
                    self.send_json({"t": "clip_files_end", "id": cid, "names": names})
            except Exception:
                pass
        self._threading.Thread(target=work, daemon=True).start()
