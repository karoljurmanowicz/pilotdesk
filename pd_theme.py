"""PilotDesk – system wizualny: neutralne szarości, jeden kolor sygnałowy (zielony = online),
czcionka Geist / Geist Mono, cienkie linie zamiast kolorowych plakietek. Logo i ikony rysowane w kodzie."""
import math
import os
import sys

from PIL import Image, ImageDraw

# kolory: (jasny motyw, ciemny motyw)
BG = ("#FAFAFA", "#09090B")
SIDEBAR = ("#F4F4F5", "#0C0C0F")
SURFACE = ("#FFFFFF", "#111114")
SURFACE_2 = ("#F4F4F5", "#17171B")
SURFACE_3 = ("#EBEBEE", "#1F1F24")
BORDER = ("#E7E7EA", "#1F1F24")
BORDER_STRONG = ("#D4D4D8", "#2C2C33")
TEXT = ("#09090B", "#EDEDF0")
TEXT_2 = ("#52525B", "#A1A1AA")
TEXT_3 = ("#8A8A93", "#6B6B75")
PRIMARY = ("#18181B", "#EDEDF0")
PRIMARY_HOVER = ("#27272A", "#FFFFFF")
PRIMARY_TEXT = ("#FAFAFA", "#09090B")
GREEN = "#3DD68C"
AMBER = "#E5A93B"
RED = "#F0574F"
DANGER_BG = ("#FEF1F1", "#231314")
DANGER_BG_HOVER = ("#FDE2E2", "#2E1718")

# zgodność ze starszymi nazwami
CARD, CARD_HOVER, INPUT = SURFACE, SURFACE_2, SURFACE_2
MUTED, ACCENT, ACCENT_HOVER = TEXT_2, PRIMARY, PRIMARY_HOVER
SUCCESS, DANGER, DANGER_HOVER, WARN = GREEN, RED, "#D9443D", AMBER
NAV_ACTIVE, NAV_HOVER = SURFACE_3, SURFACE_2
SECONDARY, SECONDARY_HOVER = SURFACE_2, SURFACE_3

SANS = "PD Geist"
SANS_MED = "PD Geist Medium"
SANS_SEMI = "PD Geist SemiBold"
MONO = "PD Geist Mono"
MONO_MED = "PD Geist Mono Medium"
FAMILY = SANS
_fonts_ok = False


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def load_fonts():
    """Ładuje dołączone czcionki Geist (prywatnie dla procesu). Wywołać przed utworzeniem okna."""
    global _fonts_ok, SANS, SANS_MED, SANS_SEMI, MONO, MONO_MED, FAMILY
    d = resource("fonts")
    files = ["PDGeist.ttf", "PDGeistMedium.ttf", "PDGeistSemiBold.ttf", "PDGeistMono.ttf", "PDGeistMonoMedium.ttf"]
    ok = os.path.isdir(d)
    if ok:
        try:
            if sys.platform == "win32":
                import ctypes
                for f in files:
                    ok &= ctypes.windll.gdi32.AddFontResourceExW(os.path.join(d, f), 0x10, 0) > 0  # FR_PRIVATE
            elif sys.platform.startswith("linux"):
                import shutil
                os.makedirs(os.path.expanduser("~/.fonts"), exist_ok=True)  # customtkinter kopiuje tu swoje czcionki
                dst = os.path.expanduser("~/.local/share/fonts/pilotdesk")
                os.makedirs(dst, exist_ok=True)
                new = False
                for f in files:
                    if not os.path.exists(os.path.join(dst, f)):
                        shutil.copy2(os.path.join(d, f), dst)
                        new = True
                if new:
                    os.system("fc-cache -f >/dev/null 2>&1")
            else:
                ok = False
        except Exception:
            ok = False
    if not ok:  # czcionki systemowe
        if sys.platform == "win32":
            SANS = SANS_MED = "Segoe UI"
            SANS_SEMI = "Segoe UI Semibold"
            MONO = MONO_MED = "Consolas"
        elif sys.platform == "darwin":
            SANS = SANS_MED = SANS_SEMI = "Helvetica Neue"
            MONO = MONO_MED = "Menlo"
        else:
            SANS = SANS_MED = SANS_SEMI = "DejaVu Sans"
            MONO = MONO_MED = "DejaVu Sans Mono"
    FAMILY = SANS
    _fonts_ok = ok
    return ok


def font(size=13, weight="normal", mono=False):
    """weight: normal | medium | bold (semibold)."""
    import customtkinter as ctk
    if mono:
        fam = MONO_MED if weight in ("medium", "bold") else MONO
    else:
        fam = {"medium": SANS_MED, "bold": SANS_SEMI}.get(weight, SANS)
    w = "bold" if (weight == "bold" and fam == SANS and SANS == SANS_SEMI) else "normal"
    return ctk.CTkFont(family=fam, size=size, weight=w)


# --------------------------------------------------------------------------- logo

_logo_cache = {}


def logo(size=256, bg=(14, 14, 17)):
    """Dwa nachodzące na siebie ekrany (Twój i zdalny) + zielona kropka „online”."""
    key = (size, bg)
    if key in _logo_cache:
        return _logo_cache[key]
    S = 512
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=112, fill=bg + (255,), outline=(255, 255, 255, 34), width=4)
    w = (237, 237, 240, 255)
    d.rounded_rectangle((120, 130, 330, 300), radius=26, outline=w, width=26)
    d.rounded_rectangle((196, 214, 400, 384), radius=28, fill=bg + (255,))
    d.rounded_rectangle((210, 228, 392, 370), radius=20, fill=w)
    d.ellipse((350, 110, 402, 162), fill=(61, 214, 140, 255))
    img = im.resize((size, size), Image.LANCZOS)
    _logo_cache[key] = img
    return img


def save_ico(path):
    logo(256).save(path, format="ICO", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48),
                                              (64, 64), (128, 128), (256, 256)])
    return path


def icon_file():
    if sys.platform == "win32":
        d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PilotDesk")
    else:
        d = os.path.join(os.path.expanduser("~"), ".local", "share", "pilotdesk")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "pilotdesk3.ico" if sys.platform == "win32" else "pilotdesk3.png")
    if not os.path.exists(p):
        save_ico(p) if sys.platform == "win32" else logo(256).save(p)
    return p


def apply_window_icon(win):
    from PIL import ImageTk

    def do():
        try:
            if sys.platform == "win32":
                win.iconbitmap(icon_file())
            else:
                win._pd_icon = ImageTk.PhotoImage(logo(64))
                win.iconphoto(False, win._pd_icon)
        except Exception:
            pass
    do()
    win.after(260, do)


def apply_dark_title_bar(win, dark=True):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


# --------------------------------------------------------------------------- ikony (linie 1.6 px w siatce 24)

class _Pen:
    def __init__(self, color, S=192, stroke=1.6):
        self.k = S / 24
        self.img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.c = color
        self.w = max(1, int(round(stroke * self.k)))

    def p(self, x, y):
        return (x * self.k, y * self.k)

    def cap(self, x, y):
        r = self.w / 2
        X, Y = self.p(x, y)
        self.d.ellipse((X - r, Y - r, X + r, Y + r), fill=self.c)

    def line(self, *pts, closed=False):
        P = [self.p(x, y) for x, y in pts]
        if closed:
            P.append(P[0])
        self.d.line(P, fill=self.c, width=self.w, joint="curve")
        for x, y in pts:
            self.cap(x, y)

    def rect(self, x, y, w, h, r=2):
        self.d.rounded_rectangle((*self.p(x, y), *self.p(x + w, y + h)), radius=r * self.k, outline=self.c, width=self.w)

    def frect(self, x, y, w, h, r=1):
        self.d.rounded_rectangle((*self.p(x, y), *self.p(x + w, y + h)), radius=r * self.k, fill=self.c)

    def circle(self, cx, cy, r, fill=False):
        box = (*self.p(cx - r, cy - r), *self.p(cx + r, cy + r))
        if fill:
            self.d.ellipse(box, fill=self.c)
        else:
            self.d.ellipse(box, outline=self.c, width=self.w)

    def arc(self, cx, cy, r, a0, a1):
        self.d.arc((*self.p(cx - r, cy - r), *self.p(cx + r, cy + r)), a0, a1, fill=self.c, width=self.w)
        for a in (a0, a1):
            self.cap(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))

    def poly(self, *pts):
        self.d.polygon([self.p(x, y) for x, y in pts], fill=self.c)


def _draw(name, P):
    if name == "monitor":
        P.rect(2.5, 3.5, 19, 13, 2); P.line((12, 16.5), (12, 20.5)); P.line((8, 20.5), (16, 20.5))
    elif name == "laptop":
        P.rect(4, 4.5, 16, 11, 1.8); P.line((2, 19.5), (22, 19.5))
    elif name == "connect":
        P.line((15, 3.5), (19, 3.5), (20.5, 5), (20.5, 19), (19, 20.5), (15, 20.5))
        P.line((3.5, 12), (14.5, 12)); P.line((10.5, 8), (14.5, 12), (10.5, 16))
    elif name == "computers":
        P.rect(3, 4, 12, 9, 1.6); P.rect(9, 11, 12, 9, 1.6)
    elif name == "settings":
        P.circle(12, 12, 3)
        P.circle(12, 12, 7)
        for i in range(8):
            a = math.radians(i * 45 + 22.5)
            P.line((12 + 7.2 * math.cos(a), 12 + 7.2 * math.sin(a)), (12 + 9.4 * math.cos(a), 12 + 9.4 * math.sin(a)))
    elif name == "folder":
        P.line((3, 6), (3, 18), (4.5, 19.5), (19.5, 19.5), (21, 18), (21, 9), (19.5, 7.5), (11.5, 7.5),
               (9.5, 4.5), (4.5, 4.5), closed=True)
    elif name == "upload":
        P.line((12, 15), (12, 3.5)); P.line((7.5, 8), (12, 3.5), (16.5, 8)); P.line((3.5, 15), (3.5, 20), (20.5, 20), (20.5, 15))
    elif name == "download":
        P.line((12, 3.5), (12, 15)); P.line((7.5, 10.5), (12, 15), (16.5, 10.5)); P.line((3.5, 15), (3.5, 20), (20.5, 20), (20.5, 15))
    elif name == "chat":
        P.line((4.5, 4.5), (19.5, 4.5), (20.5, 5.5), (20.5, 15), (19.5, 16), (10, 16), (5.5, 20), (5.5, 16),
               (4.5, 16), (3.5, 15), (3.5, 5.5), closed=True)
    elif name == "sliders":
        P.line((4, 7), (20, 7)); P.line((4, 17), (20, 17)); P.circle(9, 7, 2.2, fill=True); P.circle(15, 17, 2.2, fill=True)
    elif name == "keyboard":
        P.rect(2.5, 5.5, 19, 13, 2)
        for x in (6.5, 10, 13.5, 17):
            P.frect(x - 0.7, 9, 1.4, 1.4, 0.3)
        P.line((8, 14.5), (16, 14.5))
    elif name == "fullscreen":
        P.line((3.5, 8.5), (3.5, 3.5), (8.5, 3.5)); P.line((15.5, 3.5), (20.5, 3.5), (20.5, 8.5))
        P.line((20.5, 15.5), (20.5, 20.5), (15.5, 20.5)); P.line((8.5, 20.5), (3.5, 20.5), (3.5, 15.5))
    elif name == "exit_fullscreen":
        P.line((8.5, 3.5), (8.5, 8.5), (3.5, 8.5)); P.line((20.5, 8.5), (15.5, 8.5), (15.5, 3.5))
        P.line((3.5, 15.5), (8.5, 15.5), (8.5, 20.5)); P.line((15.5, 20.5), (15.5, 15.5), (20.5, 15.5))
    elif name == "fit":
        P.rect(3, 5, 18, 14, 2); P.line((8, 9), (8, 15)); P.line((16, 9), (16, 15))
    elif name == "refresh":
        P.arc(12, 12, 8, -40, 250); P.line((19.8, 3.8), (18.6, 7.8), (14.6, 6.8))
    elif name == "power":
        P.arc(12, 13, 8, -55, 235); P.line((12, 3), (12, 11))
    elif name == "restart":
        P.arc(12, 12, 8, 200, 500); P.line((3.2, 6.3), (4.5, 10.5), (8.6, 9.5))
    elif name == "copy":
        P.rect(8.5, 8.5, 12, 12, 2); P.line((15.5, 5.5), (15.5, 4.5), (14.5, 3.5), (4.5, 3.5), (3.5, 4.5), (3.5, 14.5), (4.5, 15.5), (5.5, 15.5))
    elif name == "eye":
        P.d.ellipse((*P.p(2.5, 6.5), *P.p(21.5, 17.5)), outline=P.c, width=P.w); P.circle(12, 12, 2.8)
    elif name == "eye_off":
        P.d.ellipse((*P.p(2.5, 6.5), *P.p(21.5, 17.5)), outline=P.c, width=P.w); P.circle(12, 12, 2.8); P.line((3.5, 3.5), (20.5, 20.5))
    elif name == "key":
        P.circle(8, 16, 4.3); P.line((11.1, 12.9), (20.5, 3.5)); P.line((17.5, 6.5), (20.5, 9.5)); P.line((15, 9), (17, 11))
    elif name == "trash":
        P.line((3.5, 6), (20.5, 6)); P.line((5.5, 6), (6.5, 20), (8, 21), (16, 21), (17.5, 20), (18.5, 6))
        P.line((9, 6), (9, 3.5), (15, 3.5), (15, 6))
    elif name == "edit":
        P.line((16, 3.5), (20.5, 8), (8.5, 20), (3.5, 20.5), (4, 15.5), closed=True)
    elif name == "plus":
        P.line((12, 5), (12, 19)); P.line((5, 12), (19, 12))
    elif name == "search":
        P.circle(10.5, 10.5, 6.5); P.line((15.5, 15.5), (20.5, 20.5))
    elif name == "clipboard":
        P.rect(5, 4.5, 14, 17, 2); P.rect(8.5, 2.5, 7, 4, 1); P.line((8.5, 12), (15.5, 12)); P.line((8.5, 16), (13, 16))
    elif name == "mouse":
        P.rect(6.5, 3, 11, 18, 5.5); P.line((12, 6.5), (12, 9.5))
    elif name == "user":
        P.circle(12, 8.5, 4); P.arc(12, 23, 8.5, 205, 335)
    elif name == "shield":
        P.line((12, 3), (19.5, 5.8), (19.5, 11), (18, 15.5), (12, 21), (6, 15.5), (4.5, 11), (4.5, 5.8), closed=True)
    elif name == "home":
        P.line((3.5, 10.5), (12, 3.5), (20.5, 10.5)); P.line((5.5, 9), (5.5, 20.5), (18.5, 20.5), (18.5, 9))
    elif name == "send":
        P.line((20.5, 3.5), (14, 20.5), (10.8, 13.2), (3.5, 10), closed=True); P.line((20.5, 3.5), (10.8, 13.2))
    elif name == "x":
        P.line((6.5, 6.5), (17.5, 17.5)); P.line((17.5, 6.5), (6.5, 17.5))
    elif name == "check":
        P.line((5, 12.5), (9.8, 17.3), (19, 7))
    elif name == "chevron_down":
        P.line((7, 9.5), (12, 14.5), (17, 9.5))
    elif name == "arrow_up":
        P.line((12, 19.5), (12, 4.5)); P.line((6.5, 10), (12, 4.5), (17.5, 10))
    elif name == "arrow_right":
        P.line((4.5, 12), (19.5, 12)); P.line((14, 6.5), (19.5, 12), (14, 17.5))
    elif name == "arrow_left":
        P.line((19.5, 12), (4.5, 12)); P.line((10, 6.5), (4.5, 12), (10, 17.5))
    elif name == "lock":
        P.rect(4.5, 10.5, 15, 10.5, 2); P.arc(12, 10, 4.3, 180, 360); P.line((7.7, 10), (7.7, 10.5)); P.line((16.3, 10), (16.3, 10.5))
    elif name == "globe":
        P.circle(12, 12, 9); P.line((3, 12), (21, 12)); P.d.ellipse((*P.p(8, 3), *P.p(16, 21)), outline=P.c, width=P.w)
    elif name == "info":
        P.circle(12, 12, 9); P.line((12, 11), (12, 16.5)); P.circle(12, 7.6, 1.1, fill=True)
    elif name == "file":
        P.line((14, 3), (6, 3), (4.5, 4.5), (4.5, 19.5), (6, 21), (18, 21), (19.5, 19.5), (19.5, 8.5), (14, 3), (14, 8.5), (19.5, 8.5))
    elif name == "speaker":
        P.line((4, 9), (7.5, 9), (12, 5), (12, 19), (7.5, 15), (4, 15), closed=True)
        P.arc(13, 12, 4, -45, 45); P.arc(13, 12, 7.5, -45, 45)
    elif name == "speaker_off":
        P.line((4, 9), (7.5, 9), (12, 5), (12, 19), (7.5, 15), (4, 15), closed=True); P.line((16, 9.5), (21, 14.5)); P.line((21, 9.5), (16, 14.5))
    elif name == "privacy":
        P.rect(2.5, 3.5, 19, 13, 2); P.frect(5, 6, 14, 8, 0.8); P.line((12, 16.5), (12, 20.5)); P.line((8, 20.5), (16, 20.5))
    elif name == "more":
        P.circle(6, 12, 1.3, fill=True); P.circle(12, 12, 1.3, fill=True); P.circle(18, 12, 1.3, fill=True)
    elif name == "zap":
        P.line((13, 3), (5, 13.5), (11.5, 13.5), (10.5, 21), (19, 10.5), (12.5, 10.5), closed=True)
    elif name == "dot":
        P.circle(12, 12, 4.5, fill=True)
    else:
        P.circle(12, 12, 8)


_icon_cache = {}


def icon_pil(name, color="#FFFFFF", px=48):
    key = (name, color, px)
    if key not in _icon_cache:
        P = _Pen(color)
        _draw(name, P)
        _icon_cache[key] = P.img.resize((px, px), Image.LANCZOS)
    return _icon_cache[key]


def icon(name, size=16, color=None):
    import customtkinter as ctk
    color = color or TEXT_2
    if isinstance(color, str):
        color = (color, color)
    px = size * 3
    return ctk.CTkImage(light_image=icon_pil(name, color[0], px), dark_image=icon_pil(name, color[1], px), size=(size, size))


def ctk_logo(size):
    import customtkinter as ctk
    img = logo(size * 3)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
