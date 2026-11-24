"""PilotDesk – elementy interfejsu (customtkinter) w stylu: neutralne powierzchnie, cienkie obramowania,
przyciski-pigułki, etykiety sekcji czcionką mono."""
import tkinter as tk

import customtkinter as ctk

import pd_theme as T


def dark():
    return ctk.get_appearance_mode() == "Dark"


def card(master, **kw):
    kw.setdefault("fg_color", T.SURFACE)
    kw.setdefault("corner_radius", 12)
    kw.setdefault("border_width", 1)
    kw.setdefault("border_color", T.BORDER)
    return ctk.CTkFrame(master, **kw)


def label(master, text="", size=13, weight="normal", color=T.TEXT, mono=False, **kw):
    return ctk.CTkLabel(master, text=text, font=T.font(size, weight, mono), text_color=color, **kw)


def hairline(master, **pack):
    f = ctk.CTkFrame(master, fg_color=T.BORDER, height=1, corner_radius=0)
    if pack:
        f.pack(**pack)
    return f


def section(master, text, padx=0, pady=(22, 10), right=None):
    """Etykieta sekcji: „OSTATNIE ─────────”."""
    f = ctk.CTkFrame(master, fg_color="transparent")
    f.pack(fill="x", padx=padx, pady=pady)
    label(f, text.upper(), 11, color=T.TEXT_3, mono=True).pack(side="left")
    if right is not None:
        right(f).pack(side="right")
    ctk.CTkFrame(f, fg_color=T.BORDER, height=1, corner_radius=0).pack(side="left", fill="x", expand=True, padx=(12, 12 if right else 0))
    return f


def primary_button(master, text, command, icon=None, height=36, **kw):
    kw.setdefault("font", T.font(13, "medium"))
    return ctk.CTkButton(master, text=text, command=command, height=height, corner_radius=height // 2,
                         fg_color=T.PRIMARY, hover_color=T.PRIMARY_HOVER, text_color=T.PRIMARY_TEXT,
                         text_color_disabled=T.TEXT_3,
                         image=T.icon(icon, 15, T.PRIMARY_TEXT) if icon else None, **kw)


def secondary_button(master, text, command, icon=None, height=34, **kw):
    kw.setdefault("font", T.font(13))
    return ctk.CTkButton(master, text=text, command=command, height=height, corner_radius=height // 2,
                         fg_color="transparent", hover_color=T.SURFACE_2, text_color=T.TEXT, border_width=1,
                         border_color=T.BORDER_STRONG, image=T.icon(icon, 15) if icon else None, **kw)


def danger_button(master, text, command, icon=None, height=34, **kw):
    kw.setdefault("font", T.font(13, "medium"))
    return ctk.CTkButton(master, text=text, command=command, height=height, corner_radius=height // 2,
                         fg_color=T.DANGER_BG, hover_color=T.DANGER_BG_HOVER, text_color=T.RED,
                         image=T.icon(icon, 15, T.RED) if icon else None, **kw)


def icon_button(master, icon, command, tip=None, size=16, **kw):
    kw.setdefault("width", 32)
    kw.setdefault("height", 32)
    kw.setdefault("corner_radius", 8)
    b = ctk.CTkButton(master, text="", image=T.icon(icon, size), command=command, fg_color="transparent",
                      hover_color=T.SURFACE_2, **kw)
    if tip:
        Tooltip(b, tip)
    return b


def entry(master, placeholder="", show=None, size=13, mono=False, **kw):
    kw.setdefault("height", 38)
    kw.setdefault("corner_radius", 8)
    return ctk.CTkEntry(master, placeholder_text=placeholder, show=show, font=T.font(size, mono=mono),
                        fg_color=T.SURFACE_2, border_color=T.BORDER, border_width=1, text_color=T.TEXT,
                        placeholder_text_color=T.TEXT_3, **kw)


def switch(master, text, variable, command=None):
    extra = {} if text else {"width": 36}
    return ctk.CTkSwitch(master, text=text, **extra, variable=variable, command=command, font=T.font(13), text_color=T.TEXT,
                         progress_color=T.GREEN, fg_color=T.SURFACE_3, button_color=("#FFFFFF", "#EDEDF0"),
                         button_hover_color=("#FFFFFF", "#FFFFFF"), switch_width=34, switch_height=18)


def checkbox(master, text, variable):
    return ctk.CTkCheckBox(master, text=text, variable=variable, font=T.font(13), text_color=T.TEXT,
                           fg_color=T.PRIMARY, hover_color=T.PRIMARY_HOVER, border_color=T.BORDER_STRONG,
                           checkmark_color=T.PRIMARY_TEXT, corner_radius=5, checkbox_width=18, checkbox_height=18,
                           border_width=1)


def dot(master, color, size=8):
    return ctk.CTkLabel(master, text="", image=T.icon("dot", size + 4, color), width=size + 4)


def pill(master, text, color):
    f = ctk.CTkFrame(master, fg_color=T.SURFACE_2, corner_radius=11, height=24, border_width=1, border_color=T.BORDER)
    d = dot(f, color, 7)
    d.pack(side="left", padx=(8, 4), pady=2)
    lbl = ctk.CTkLabel(f, text=text, font=T.font(12), text_color=T.TEXT_2, height=20)
    lbl.pack(side="left", padx=(0, 10))

    def set(text, color):
        lbl.configure(text=text)
        d.configure(image=T.icon("dot", 11, color))
    f.set = set
    return f


class Chip(ctk.CTkFrame):
    """Przycisk-przełącznik z paskiem stanu pod ikoną (zielony = włączone)."""

    def __init__(self, master, icon, command, tip=None, toggle=False, on=False):
        super().__init__(master, fg_color="transparent", width=34, height=38)
        self.pack_propagate(False)
        self.icon_name = icon
        self.toggle = toggle
        self.btn = ctk.CTkButton(self, text="", image=T.icon(icon, 16), command=command, width=32, height=30,
                                 corner_radius=8, fg_color="transparent", hover_color=T.SURFACE_2)
        self.btn.pack(side="top")
        self.bar = ctk.CTkFrame(self, fg_color="transparent", height=2, width=14, corner_radius=1)
        self.bar.pack(side="top", pady=(2, 0))
        if tip:
            Tooltip(self.btn, tip)
        self.set(on)

    def set(self, on, color=T.GREEN):
        self.on = on
        if self.toggle:
            self.bar.configure(fg_color=color if on else "transparent")
            self.btn.configure(fg_color=T.SURFACE_2 if on else "transparent", image=T.icon(self.icon_name, 16, T.TEXT if on else T.TEXT_2))

    def set_icon(self, name):
        self.icon_name = name
        self.btn.configure(image=T.icon(name, 16, T.TEXT if self.on and self.toggle else T.TEXT_2))


def popup_menu(widget, items):
    """items: [(etykieta, funkcja)] / None = separator. Etykieta zaczynająca się od „✓ ” = zaznaczona."""
    d = dark()
    m = tk.Menu(widget, tearoff=False, bg="#141417" if d else "#FFFFFF", fg="#EDEDF0" if d else "#09090B",
                activebackground="#232328" if d else "#F0F0F2", activeforeground="#FFFFFF" if d else "#09090B",
                bd=1, relief="solid", font=(T.SANS, 10), activeborderwidth=0)
    for it in items:
        if it is None:
            m.add_separator()
        else:
            m.add_command(label="  " + it[0] + "      ", command=it[1])
    m.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height() + 4)


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.win, self.job = widget, text, None, None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")

    def _enter(self, _e=None):
        self.job = self.widget.after(500, self._show)

    def _show(self):
        if self.win:
            return
        self.win = tk.Toplevel(self.widget)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        tk.Label(self.win, text=self.text, bg="#EDEDF0" if dark() else "#18181B", fg="#09090B" if dark() else "#FAFAFA",
                 font=(T.SANS, 9), padx=8, pady=3).pack()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.win.geometry(f"+{x}+{y}")

    def _leave(self, _e=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.win:
            self.win.destroy()
            self.win = None


class Toast:
    _active = []

    def __init__(self, root, text, kind="info", ms=3500):
        color = {"info": T.TEXT_2, "ok": T.GREEN, "error": T.RED, "warn": T.AMBER}.get(kind, T.TEXT_2)
        f = ctk.CTkFrame(root, fg_color=T.SURFACE, corner_radius=10, border_width=1, border_color=T.BORDER_STRONG)
        dot(f, color, 7).pack(side="left", padx=(12, 6))
        ctk.CTkLabel(f, text=text, font=T.font(12), text_color=T.TEXT, wraplength=340, justify="left").pack(
            side="left", padx=(0, 14), pady=9)
        self.f = f
        Toast._active.append(self)
        self._place()
        root.after(ms, self.close)

    def _place(self):
        y = -18
        for t in reversed(Toast._active):
            try:
                t.f.place(relx=1.0, rely=1.0, x=-18, y=y, anchor="se")
                t.f.lift()
                t.f.update_idletasks()
                y -= t.f.winfo_height() + 8
            except Exception:
                pass

    def close(self):
        if self in Toast._active:
            Toast._active.remove(self)
        try:
            self.f.destroy()
        except Exception:
            pass
        if Toast._active:
            Toast._active[0]._place()


class Dialog(ctk.CTkToplevel):
    def __init__(self, master, title, subtitle="", icon="info", width=420):
        super().__init__(master)
        self.withdraw()
        self.title(title)
        self.configure(fg_color=T.SURFACE)
        self.resizable(False, False)
        self.result = None
        T.apply_window_icon(self)
        T.apply_dark_title_bar(self, dark())
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(22, 20))
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text="", image=T.icon(icon, 18, T.TEXT)).pack(side="left", anchor="n", pady=(2, 0))
        txt = ctk.CTkFrame(head, fg_color="transparent")
        txt.pack(side="left", padx=12, fill="x", expand=True)
        label(txt, title, 15, "bold").pack(anchor="w")
        if subtitle:
            label(txt, subtitle, 12, color=T.TEXT_2, wraplength=width - 100, justify="left").pack(anchor="w", pady=(2, 0))
        self.body = ctk.CTkFrame(body, fg_color="transparent")
        self.body.pack(fill="both", expand=True, pady=(14, 0))
        self.buttons = ctk.CTkFrame(body, fg_color="transparent")
        self.buttons.pack(fill="x", pady=(18, 0))
        self.width = width
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def add_buttons(self, ok_text="OK", cancel_text="Anuluj", danger=False):
        mk = danger_button if danger else primary_button
        mk(self.buttons, ok_text, self.ok, width=110).pack(side="right")
        if cancel_text:
            secondary_button(self.buttons, cancel_text, self.cancel, width=100).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self.ok())

    def run(self):
        self.update_idletasks()
        m = self.master.winfo_toplevel()
        w = max(self.width, self.winfo_reqwidth())
        h = self.winfo_reqheight()
        x = m.winfo_rootx() + (m.winfo_width() - w) // 2
        y = m.winfo_rooty() + (m.winfo_height() - h) // 3
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        try:
            if m.winfo_viewable():
                self.transient(m)
        except tk.TclError:
            pass
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.after(60, self.focus_first)
        self.wait_window()
        return self.result

    def focus_first(self):
        pass

    def ok(self):
        self.result = True
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


class PasswordDialog(Dialog):
    def __init__(self, master):
        super().__init__(master, "Hasło dostępu", "Hasło do tego komputera. Najlepiej 12 lub więcej znaków.", icon="key")
        self.e1 = entry(self.body, "Nowe hasło", show="•")
        self.e1.pack(fill="x")
        self.e2 = entry(self.body, "Powtórz hasło", show="•")
        self.e2.pack(fill="x", pady=(8, 0))
        self.err = label(self.body, "", 12, color=T.RED)
        self.err.pack(anchor="w", pady=(6, 0))
        self.add_buttons("Zapisz")

    def focus_first(self):
        self.e1.focus_set()

    def ok(self):
        p1, p2 = self.e1.get(), self.e2.get()
        if len(p1) < 8:
            self.err.configure(text="Hasło musi mieć co najmniej 8 znaków.")
            return
        if p1 != p2:
            self.err.configure(text="Hasła się różnią.")
            return
        self.result = p1
        self.destroy()


class InputDialog(Dialog):
    def __init__(self, master, title, prompt, initial="", icon="edit"):
        super().__init__(master, title, prompt, icon=icon)
        self.e = entry(self.body, "")
        self.e.insert(0, initial)
        self.e.pack(fill="x")
        self.add_buttons("OK")

    def focus_first(self):
        self.e.focus_set()
        self.e.select_range(0, "end")

    def ok(self):
        self.result = self.e.get().strip() or None
        self.destroy()


class ConfirmDialog(Dialog):
    def __init__(self, master, title, text, ok_text="Tak", danger=False, icon="info", check=None, cancel_text="Anuluj"):
        super().__init__(master, title, text, icon=icon)
        self.var = tk.BooleanVar(value=False)
        if check:
            checkbox(self.body, check, self.var).pack(anchor="w")
        self.add_buttons(ok_text, cancel_text=cancel_text, danger=danger)

    def ok(self):
        self.result = (True, self.var.get())
        self.destroy()


def ask_password(master):
    return PasswordDialog(master).run()


def ask_string(master, title, prompt, initial="", icon="edit"):
    return InputDialog(master, title, prompt, initial, icon).run()


def confirm(master, title, text, ok_text="Tak", danger=False, icon="info", check=None, cancel_text="Anuluj"):
    r = ConfirmDialog(master, title, text, ok_text, danger, icon, check, cancel_text).run()
    return r if check else bool(r)


def info(master, title, text, icon="info"):
    d = Dialog(master, title, text, icon=icon)
    d.add_buttons("OK", cancel_text=None)
    d.run()


class AskDialog(ctk.CTkToplevel):
    """Prośba o połączenie bez hasła: Akceptuj / Odrzuć, z kodem weryfikacyjnym i odliczaniem."""

    def __init__(self, master, client, peer, code, on_answer, timeout=55):
        super().__init__(master)
        self.on_answer = on_answer
        self.done = False
        self.left = timeout
        self.title("Prośba o połączenie")
        self.configure(fg_color=T.SURFACE)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        T.apply_window_icon(self)
        T.apply_dark_title_bar(self, dark())
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(fill="both", expand=True, padx=26, pady=22)
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text="", image=T.ctk_logo(34)).pack(side="left")
        t = ctk.CTkFrame(top, fg_color="transparent")
        t.pack(side="left", padx=12)
        label(t, "Ktoś chce połączyć się z tym komputerem", 14, "bold").pack(anchor="w")
        label(t, f"{client}  ·  {peer}", 12, color=T.TEXT_2).pack(anchor="w")
        section(f, "kod weryfikacyjny", pady=(18, 6))
        label(f, f"{code[:3]} {code[3:]}", 30, mono=True).pack(anchor="w")
        label(f, "Porównaj z kodem na ekranie osoby, która się łączy. Akceptuj tylko, gdy wiesz, kto to jest.",
              12, color=T.TEXT_2, wraplength=360, justify="left").pack(anchor="w", pady=(4, 0))
        b = ctk.CTkFrame(f, fg_color="transparent")
        b.pack(fill="x", pady=(20, 0))
        primary_button(b, "Akceptuj", lambda: self.answer(True), width=120).pack(side="right")
        self.rej = secondary_button(b, f"Odrzuć ({self.left})", lambda: self.answer(False), width=120)
        self.rej.pack(side="right", padx=8)
        self.protocol("WM_DELETE_WINDOW", lambda: self.answer(False))
        self.update_idletasks()
        w, h = 430, self.winfo_reqheight()
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}+{(self.winfo_screenheight() - h) // 3}")
        self.after(1000, self._tick)
        self.lift()
        self.focus_force()

    def _tick(self):
        if self.done:
            return
        self.left -= 1
        if self.left <= 0:
            self.answer(False)
            return
        self.rej.configure(text=f"Odrzuć ({self.left})")
        self.after(1000, self._tick)

    def answer(self, ok):
        if self.done:
            return
        self.done = True
        try:
            self.on_answer(ok)
        finally:
            self.destroy()
