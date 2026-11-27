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


# --------------------------------------------------------------------------- wstrzykiwanie myszy (SendInput)
# Własna implementacja zamiast pynput: kliknięcie idzie razem z ruchem w jednym zdarzeniu (dokładnie w punkcie
# kursora), sprawdzamy wynik SendInput i kod błędu, a zdarzenia mają znacznik PD_INPUT_TAG (dwExtraInfo).
PD_INPUT_TAG = 0x50444B31  # "PDK1"
_MOUSE = {}


def _mouse_api():
    if _MOUSE:
        return _MOUSE
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    u32 = ctypes.WinDLL("user32", use_last_error=True)  # osobny obiekt – nie zmieniamy argtypes pynput
    u32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    u32.SendInput.restype = wintypes.UINT
    u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    u32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _MOUSE.update(INPUT=INPUT, MOUSEINPUT=MOUSEINPUT, u32=u32)
    return _MOUSE


MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
_BTN_FLAGS = {("left", True): 0x0002, ("left", False): 0x0004, ("right", True): 0x0008, ("right", False): 0x0010,
              ("middle", True): 0x0020, ("middle", False): 0x0040}


def virtual_screen():
    """(x, y, szer, wys) całego pulpitu wirtualnego w pikselach widzianych przez ten proces."""
    if not IS_WIN:
        return (0, 0, 0, 0)
    g = _mouse_api()["u32"].GetSystemMetrics
    return (g(76), g(77), g(78), g(79))  # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN


def _send_mouse(flags, x=None, y=None, data=0):
    """Zwraca (ok, kod_błędu)."""
    api = _mouse_api()
    dx = dy = 0
    if x is not None:
        vx, vy, vw, vh = virtual_screen()
        if vw > 0 and vh > 0:
            # wartości 0..65535 – zaokrąglenie w górę daje dokładnie ten piksel po przeliczeniu przez Windows
            dx = min(max(((x - vx) * 65536 + vw - 1) // vw, 0), 65535)
            dy = min(max(((y - vy) * 65536 + vh - 1) // vh, 0), 65535)
            flags |= MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    inp = api["INPUT"](type=0)
    inp.mi = api["MOUSEINPUT"](dx=dx, dy=dy, mouseData=ctypes.c_uint32(int(data)).value, dwFlags=flags, time=0,
                               dwExtraInfo=PD_INPUT_TAG)
    n = api["u32"].SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    return (n == 1, 0 if n == 1 else ctypes.get_last_error())


def mouse_move(x, y):
    """Ustawia kursor dokładnie w (x, y) i wysyła zdarzenie ruchu (programy widzą ruch jak z myszy)."""
    api = _mouse_api()
    api["u32"].SetCursorPos(int(x), int(y))
    return _send_mouse(0, int(x), int(y))


def mouse_button(x, y, button, down):
    """Wciśnięcie/puszczenie przycisku w punkcie (x, y). Zwraca (ok, kod_błędu)."""
    flag = _BTN_FLAGS.get((button, bool(down)))
    if flag is None:
        return (False, 87)
    if x is not None:
        _mouse_api()["u32"].SetCursorPos(int(x), int(y))
    return _send_mouse(flag, None if x is None else int(x), None if y is None else int(y))


def mouse_wheel(dx, dy):
    ok, err = True, 0
    if dy:
        ok, err = _send_mouse(MOUSEEVENTF_WHEEL, data=int(dy) * 120)
    if dx:
        ok2, err2 = _send_mouse(MOUSEEVENTF_HWHEEL, data=int(dx) * 120)
        ok, err = ok and ok2, err or err2
    return ok, err


def dpi_info():
    """Opis trybu DPI procesu (do dziennika – kliknięcia w złym miejscu przy skalowaniu 125–150%)."""
    if not IS_WIN:
        return ""
    parts = []
    try:
        aw = ctypes.c_int(-1)
        ctypes.WinDLL("shcore").GetProcessDpiAwareness(None, ctypes.byref(aw))
        parts.append(f"DPI-awareness={aw.value}")
    except Exception as e:
        parts.append(f"DPI-awareness=? ({e})")
    try:
        parts.append(f"ekran wirtualny={virtual_screen()}")
        parts.append(f"DPI systemu={ctypes.WinDLL('user32').GetDpiForSystem()}")
    except Exception:
        pass
    return ", ".join(parts)


# --------------------------------------------------------------------------- rozdzielczość ekranu
_DISP = {}


def _disp_api():
    if _DISP:
        return _DISP

    class DEVMODEW(ctypes.Structure):
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
                    ("dmFields", wintypes.DWORD), ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                    ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                    ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
                    ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                    ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                    ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                    ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
                    ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
                    ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    u = ctypes.WinDLL("user32", use_last_error=True)
    u.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
    u.EnumDisplaySettingsW.restype = wintypes.BOOL
    u.ChangeDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW), wintypes.HWND,
                                           wintypes.DWORD, ctypes.c_void_p]
    u.ChangeDisplaySettingsExW.restype = ctypes.c_long
    u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    u.MonitorFromPoint.restype = wintypes.HANDLE
    u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFOEXW)]
    u.GetMonitorInfoW.restype = wintypes.BOOL
    _DISP.update(DEVMODEW=DEVMODEW, MONITORINFOEXW=MONITORINFOEXW, u=u)
    return _DISP


def display_device_at(x, y):
    """Nazwa urządzenia (np. \\\\.\\DISPLAY1) monitora, na którym leży punkt (x, y)."""
    api = _disp_api()
    hmon = api["u"].MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)  # MONITOR_DEFAULTTONEAREST
    mi = api["MONITORINFOEXW"]()
    mi.cbSize = ctypes.sizeof(mi)
    if not api["u"].GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    return mi.szDevice


def _devmode(device, i):
    api = _disp_api()
    dm = api["DEVMODEW"]()
    dm.dmSize = ctypes.sizeof(dm)
    return dm if api["u"].EnumDisplaySettingsW(device, i, ctypes.byref(dm)) else None


def display_modes(device):
    """(lista (szer, wys) od największej, bieżąca (szer, wys)). Tylko tryby o bieżącej głębi kolorów."""
    cur = _devmode(device, 0xFFFFFFFF)  # ENUM_CURRENT_SETTINGS
    if cur is None:
        return [], None
    seen = set()
    i = 0
    while True:
        dm = _devmode(device, i)
        if dm is None or i > 2000:
            break
        i += 1
        if dm.dmBitsPerPel == cur.dmBitsPerPel and dm.dmPelsWidth >= 800 and dm.dmPelsHeight >= 600:
            seen.add((int(dm.dmPelsWidth), int(dm.dmPelsHeight)))
    return sorted(seen, key=lambda m: (-m[0] * m[1], -m[0])), (int(cur.dmPelsWidth), int(cur.dmPelsHeight))


DISP_ERRORS = {1: "wymaga ponownego uruchomienia", -1: "sterownik odmówił", -2: "nieobsługiwany tryb",
               -3: "nie można zapisać", -4: "błędne parametry", -5: "błędne parametry", -6: "nieobsługiwany tryb"}


def set_display_mode(device, w, h):
    """Zmienia rozdzielczość tymczasowo (bez zapisu w ustawieniach Windows). Zwraca (ok, opis_błędu)."""
    api = _disp_api()
    dm = _devmode(device, 0xFFFFFFFF)
    if dm is None:
        return False, "brak informacji o monitorze"
    dm.dmPelsWidth, dm.dmPelsHeight = int(w), int(h)
    dm.dmFields = 0x00080000 | 0x00100000  # DM_PELSWIDTH | DM_PELSHEIGHT
    r = api["u"].ChangeDisplaySettingsExW(device, ctypes.byref(dm), None, 0x00000002, None)  # CDS_TEST
    if r == 0:
        r = api["u"].ChangeDisplaySettingsExW(device, ctypes.byref(dm), None, 0, None)
    return r == 0, DISP_ERRORS.get(r, f"kod {r}")


def restore_display_mode(device):
    """Przywraca rozdzielczość zapisaną w ustawieniach Windows."""
    api = _disp_api()
    return api["u"].ChangeDisplaySettingsExW(device, None, None, 0, None) == 0


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


def window_info_at(x, y):
    """(tytuł, czy działa jako administrator) okna głównego pod punktem (x, y) – tam trafia kliknięcie."""
    if not IS_WIN:
        return "", False
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.WindowFromPoint.argtypes = [wintypes.POINT]
    u.WindowFromPoint.restype = wintypes.HWND
    u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetAncestor.restype = wintypes.HWND
    hwnd = u.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hwnd:
        return "", False
    return _window_elevation(u.GetAncestor(hwnd, 2) or hwnd)  # GA_ROOT


def foreground_info():
    """(tytuł okna na pierwszym planie, czy jego proces działa jako administrator). Tylko Windows."""
    if not IS_WIN:
        return "", False
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", False
    return _window_elevation(hwnd)


def _window_elevation(hwnd):
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
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
