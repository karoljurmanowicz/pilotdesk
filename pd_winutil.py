"""PilotDesk – funkcje systemowe: tryb prywatności, restart, przełączanie pulpitu (ekran logowania/UAC),
uruchamianie z uprawnieniami administratora."""
import os
import subprocess
import sys
import threading

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                    ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32)]

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.BeginPaint.restype = wintypes.HDC
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD)]
    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.BlockInput.argtypes = [wintypes.BOOL]
    gdi32.GetStockObject.argtypes = [ctypes.c_int]
    gdi32.GetStockObject.restype = wintypes.HGDIOBJ
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

WDA_EXCLUDEFROMCAPTURE = 0x11


class PrivacyScreen:
    """Czarna plansza na monitorach sterowanego komputera, NIEWIDOCZNA dla przechwytywania ekranu
    (SetWindowDisplayAffinity) i przepuszczająca kliknięcia (okno warstwowe + WS_EX_TRANSPARENT).
    Wymaga Windows 10 2004 lub nowszego."""

    def __init__(self):
        self.hwnd = None
        self.ok = None
        self.err = ""
        self._ready = threading.Event()
        self._proc = None

    def start(self):
        if not IS_WIN:
            return False, "Tryb prywatności działa tylko w Windows."
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(5)
        return bool(self.ok), self.err

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE
            self.hwnd = None

    def _run(self):
        WM_PAINT, WM_DESTROY, WM_TIMER, WM_CLOSE, WM_MOUSEACTIVATE = 0x000F, 0x0002, 0x0113, 0x0010, 0x0021
        HWND_TOPMOST = wintypes.HWND(-1)

        def wndproc(hwnd, msg, wp, lp):
            if msg == WM_PAINT:
                ps = PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                rc = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rc))
                user32.FillRect(hdc, ctypes.byref(rc), gdi32.GetStockObject(4))  # BLACK_BRUSH
                gdi32.SetTextColor(hdc, 0x00706B6B)
                gdi32.SetBkMode(hdc, 1)
                font = gdi32.CreateFontW(-22, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
                old = gdi32.SelectObject(hdc, font)
                user32.DrawTextW(hdc, "Ten komputer jest obsługiwany zdalnie (PilotDesk)", -1, ctypes.byref(rc),
                                 0x1 | 0x4 | 0x20)  # DT_CENTER | DT_VCENTER | DT_SINGLELINE
                gdi32.SelectObject(hdc, old)
                gdi32.DeleteObject(font)
                user32.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if msg == WM_TIMER:  # ciągle na wierzchu
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
                return 0
            if msg == WM_MOUSEACTIVATE:
                return 3  # MA_NOACTIVATE
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wp, lp)

        self._proc = WNDPROC(wndproc)
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.hbrBackground = gdi32.GetStockObject(4)
        wc.lpszClassName = "PilotDeskPrivacy"
        user32.RegisterClassExW(ctypes.byref(wc))
        x, y = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)  # wirtualny ekran (wszystkie monitory)
        w, h = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        ex = 0x00000008 | 0x00000080 | 0x08000000 | 0x00080000 | 0x00000020  # TOPMOST TOOLWINDOW NOACTIVATE LAYERED TRANSPARENT
        hwnd = user32.CreateWindowExW(ex, "PilotDeskPrivacy", "PilotDesk", 0x80000000, x, y, w, h,
                                      None, None, hinst, None)
        if not hwnd:
            self.ok, self.err = False, "Nie udało się utworzyć okna prywatności."
            self._ready.set()
            return
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x2)  # w pełni nieprzezroczyste, ale „przeklikiwalne”
        if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            user32.DestroyWindow(hwnd)
            self.ok, self.err = False, "Ten Windows nie obsługuje trybu prywatności (wymagany Windows 10 2004+)."
            self._ready.set()
            return
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        user32.SetTimer(hwnd, 1, 1000, None)
        self.hwnd = hwnd
        self.ok = True
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def block_input(on):
    """Blokuje lokalną mysz/klawiaturę (działa tylko z uprawnieniami administratora/usługi).
    Wywoływać z wątku, który wstrzykuje zdarzenia zdalne."""
    if not IS_WIN:
        return False
    return bool(user32.BlockInput(bool(on)))


_current_desktop = {"name": None}


def _desktop_name(h):
    buf = ctypes.create_unicode_buffer(256)
    n = wintypes.DWORD()
    if user32.GetUserObjectInformationW(h, 2, buf, ctypes.sizeof(buf), ctypes.byref(n)):  # UOI_NAME
        return buf.value
    return ""


def sync_input_desktop():
    """Przełącza bieżący wątek na pulpit, który aktualnie dostaje wejście (Default / Winlogon / UAC).
    Zwraca True, gdy pulpit się zmienił. Ma sens tylko w procesie agenta usługi (konto SYSTEM)."""
    if not IS_WIN:
        return False
    h = user32.OpenInputDesktop(0, False, 0x10000000)  # GENERIC_ALL
    if not h:
        return False
    name = _desktop_name(h)
    cur = _desktop_name(user32.GetThreadDesktop(kernel32.GetCurrentThreadId()))
    if name and name != cur:
        if user32.SetThreadDesktop(h):
            return True
    user32.CloseDesktop(h)
    return False


def foreground_info():
    """(tytuł okna na pierwszym planie, czy jego proces działa jako administrator). Tylko Windows."""
    if not IS_WIN:
        return "", False
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", False
    buf = ctypes.create_unicode_buffer(200)
    user32.GetWindowTextW(hwnd, buf, 200)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return buf.value, False
    try:
        tok = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
            return buf.value, True  # brak dostępu do tokenu = proces o wyższych uprawnieniach
        try:
            elev = wintypes.DWORD()
            ret = wintypes.DWORD()
            ok = advapi32.GetTokenInformation(tok, 20, ctypes.byref(elev), 4, ctypes.byref(ret))  # TokenElevation
            return buf.value, bool(ok and elev.value)
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def reboot(delay=3):
    if IS_WIN:
        subprocess.Popen(["shutdown", "/r", "/t", str(delay), "/c", "PilotDesk: zdalny restart"],
                         creationflags=0x08000000)
    elif sys.platform == "darwin":
        subprocess.Popen(["osascript", "-e", 'tell app "System Events" to restart'])
    else:
        subprocess.Popen(["systemctl", "reboot"])


def lock_workstation():
    if IS_WIN:
        user32.LockWorkStation()


def is_admin():
    if not IS_WIN:
        return os.geteuid() == 0
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_elevated(exe, args, wait=True):
    """Uruchamia program jako administrator (okno UAC). Zwraca kod wyjścia albo None."""
    if not IS_WIN:
        raise OSError("tylko Windows")

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = args
    info.nShow = 0
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise OSError("Anulowano lub brak uprawnień administratora.")
    if not wait or not info.hProcess:
        return None
    kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    return code.value
