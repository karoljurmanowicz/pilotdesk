#!/usr/bin/env python3
"""PilotDesk – zdalny pulpit do łączenia się z własnymi komputerami.

  PilotDesk.exe / python pilotdesk.py   okno programu
  --minimized                           start w tle (autostart)
  --host                                tylko udostępnianie, bez okna (konsola)
  --set-password / --relay ADRES / --relay-key K / --autostart on|off / --enable / --show-id
  --uninstall                           odinstaluj (Windows)
Wewnętrzne: --service, --agent, --install-service, --uninstall-service, --service-update, --apply-update
"""
import argparse
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pd_install as INST  # noqa: E402
from pd_common import (  # noqa: E402
    DEFAULT_PORT, VERSION, AuthError, b64d, b64e, config_path, derive_password_key, ensure_host_identity,
    format_id, get_local_ips, has_password, host_config_path, hostname, load_config, machine_config_path,
    open_tcp, parse_target, relay_connect_viewer, save_config, send_wol, service_mode, set_host_password,
    update_source, username, viewer_handshake,
)


# --------------------------------------------------------------------------- tryb konsolowy

def print_ids(cfg):
    print(f"ID (przez serwer pośredniczący): {format_id(cfg['host_id'])}" + ("" if cfg.get("relay") else "   [serwer nie ustawiony]"))
    port = cfg.get("listen_port", DEFAULT_PORT)
    print("Adresy bezpośrednie: " + ", ".join(f"{ip}:{port}" for ip in get_local_ips()))


def run_headless(cfg):
    from pd_host import HostService
    if not has_password(cfg):
        print("Najpierw ustaw hasło:  pilotdesk --set-password")
        sys.exit(1)
    svc = HostService(cfg)
    svc.start()
    print_ids(cfg)
    print("Udostępnianie działa. Ctrl+C kończy.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        svc.stop()


def cli_set_password(cfg, path=None):
    import getpass
    while True:
        p1 = getpass.getpass("Nowe hasło dostępu (min. 8 znaków): ")
        if len(p1) < 8:
            print("Za krótkie.")
            continue
        if getpass.getpass("Powtórz hasło: ") != p1:
            print("Hasła się różnią.")
            continue
        break
    set_host_password(cfg, p1)
    save_config(cfg, path)
    print("Hasło zapisane.")


def ago(ts):
    if not ts:
        return ""
    d = time.time() - ts
    if d < 120:
        return "przed chwilą"
    if d < 3600:
        return f"{int(d // 60)} min temu"
    if d < 86400:
        return f"{int(d // 3600)} godz. temu"
    return f"{int(d // 86400)} dni temu"


# --------------------------------------------------------------------------- GUI

def init_ctk(cfg):
    import customtkinter as ctk
    import pd_theme as T
    T.load_fonts()
    ctk.set_appearance_mode({"dark": "dark", "light": "light", "system": "system"}.get(cfg.get("theme", "dark"), "dark"))
    ctk.set_default_color_theme("blue")
    return ctk


class NavItem:
    def __init__(self, app, master, key, text, icon):
        import customtkinter as ctk
        T, U = app.T, app.U
        self.app, self.key, self.icon = app, key, icon
        self.f = ctk.CTkFrame(master, fg_color="transparent", corner_radius=8, height=34)
        self.f.pack(fill="x", padx=10, pady=1)
        self.f.pack_propagate(False)
        self.ic = ctk.CTkLabel(self.f, text="", image=T.icon(icon, 16), width=20)
        self.ic.pack(side="left", padx=(10, 8))
        self.lbl = ctk.CTkLabel(self.f, text=text, font=T.font(13), text_color=T.TEXT_2, height=30)
        self.lbl.pack(side="left")
        self.badge = ctk.CTkLabel(self.f, text="", font=T.font(11, mono=True), text_color=T.TEXT_3, height=30)
        self.badge.pack(side="right", padx=10)
        self.active = False
        for w in (self.f, self.ic, self.lbl, self.badge):
            w.bind("<Button-1>", lambda e: app.show_page(key))
            w.bind("<Enter>", lambda e: (not self.active) and self.f.configure(fg_color=T.SURFACE_2))
            w.bind("<Leave>", lambda e: (not self.active) and self.f.configure(fg_color="transparent"))

    def set_active(self, on):
        T = self.app.T
        self.active = on
        self.f.configure(fg_color=T.SURFACE_3 if on else "transparent")
        self.lbl.configure(text_color=T.TEXT if on else T.TEXT_2, font=T.font(13, "medium" if on else "normal"))
        self.ic.configure(image=T.icon(self.icon, 16, T.TEXT if on else T.TEXT_2))

    def set_badge(self, text="", dot=None):
        T = self.app.T
        if dot:
            self.badge.configure(text="", image=T.icon("dot", 10, dot))
        else:
            self.badge.configure(text=text, image=None)


class App:
    def __init__(self, root, cfg, ext_queue=None, minimized=False):
        import customtkinter as ctk
        import pd_theme as T
        import pd_ui as U
        self.ctk, self.T, self.U = ctk, T, U
        self.root = root
        self.cfg = cfg
        self.ext_queue = ext_queue
        self.host = None
        self.events = queue.Queue()
        self.host_chats = {}
        self.banner = None
        self.tray = None
        self.tray_notified = False
        self.connecting = False
        self.sessions_win = None
        self.update_info = None
        self._load_host_cfg()

        root.title("PilotDesk")
        root.geometry("1100x720")
        root.minsize(980, 640)
        root.configure(fg_color=T.BG)
        T.apply_window_icon(root)
        T.apply_dark_title_bar(root, ctk.get_appearance_mode() == "Dark")
        root.grid_columnconfigure(2, weight=1)
        root.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        ctk.CTkFrame(root, fg_color=T.BORDER, width=1, corner_radius=0).grid(row=0, column=1, sticky="ns")
        self.content = ctk.CTkFrame(root, fg_color=T.BG, corner_radius=0)
        self.content.grid(row=0, column=2, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.pages = {}
        self._build_connect_page()
        self._build_computers_page()
        self._build_access_page()
        self._build_settings_page()
        self.show_page("connect")

        if self.service:
            self.start_host()
        elif self.hcfg.get("host_enabled") and (has_password(self.hcfg) or self.hcfg.get("ask_enabled", True)):
            self.start_host()
        self._refresh_host()
        self._setup_tray()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)
        root.after(15000, self._auto_update_tick)
        if minimized:
            root.withdraw() if self.tray else root.iconify()

    def _load_host_cfg(self):
        self.service = service_mode()
        if self.service:
            self.hpath = machine_config_path()
            self.hcfg = load_config(self.hpath)
            if ensure_host_identity(self.hcfg):
                self._save_host()
        else:
            self.hpath = None
            self.hcfg = self.cfg

    def _save_host(self):
        save_config(self.hcfg, self.hpath)

    # ================================================================ szkielet
    def _build_sidebar(self):
        ctk, T, U = self.ctk, self.T, self.U
        sb = ctk.CTkFrame(self.root, fg_color=T.SIDEBAR, corner_radius=0, width=232)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.pack_propagate(False)
        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(20, 18))
        ctk.CTkLabel(head, text="", image=T.ctk_logo(28)).pack(side="left")
        U.label(head, "PilotDesk", 15, "bold").pack(side="left", padx=10)
        U.label(head, VERSION, 11, color=T.TEXT_3, mono=True).pack(side="right")
        self.nav = {}

        def group(title):
            U.label(sb, title.upper(), 10, color=T.TEXT_3, mono=True).pack(anchor="w", padx=22, pady=(14, 4))

        group("połączenia")
        self.nav["connect"] = NavItem(self, sb, "connect", "Połącz", "connect")
        self.nav["computers"] = NavItem(self, sb, "computers", "Komputery", "computers")
        group("ten komputer")
        self.nav["access"] = NavItem(self, sb, "access", "Dostęp", "shield")
        group("aplikacja")
        self.nav["settings"] = NavItem(self, sb, "settings", "Ustawienia", "settings")

        me = U.card(sb, fg_color=T.SURFACE, corner_radius=10)
        me.pack(side="bottom", fill="x", padx=12, pady=12)
        mi = ctk.CTkFrame(me, fg_color="transparent")
        mi.pack(fill="x", padx=12, pady=10)
        top = ctk.CTkFrame(mi, fg_color="transparent")
        top.pack(fill="x")
        self.me_dot = U.dot(top, T.TEXT_3, 7)
        self.me_dot.pack(side="left")
        U.label(top, hostname()[:20], 12, "medium").pack(side="left", padx=6)
        self.me_sub = U.label(mi, "", 11, color=T.TEXT_3, mono=True)
        self.me_sub.pack(anchor="w", pady=(2, 0))
        self.update_btn = U.secondary_button(sb, "Aktualizuj", self._install_update_now, icon="download", height=30)

    def show_page(self, key):
        for k, item in self.nav.items():
            item.set_active(k == key)
        for k, page in self.pages.items():
            if k == key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_forget()
        self.current_page = key

    def show_connect(self):
        self.show_window()
        self.show_page("connect")
        self.target.focus_set()

    def _page(self, key, title, subtitle):
        ctk, T, U = self.ctk, self.T, self.U
        p = ctk.CTkScrollableFrame(self.content, fg_color=T.BG, corner_radius=0, scrollbar_button_color=T.BG,
                                   scrollbar_button_hover_color=T.BORDER_STRONG)
        hdr = ctk.CTkFrame(p, fg_color="transparent")
        hdr.pack(fill="x", padx=40, pady=(34, 6))
        U.label(hdr, title, 22, "bold").pack(anchor="w")
        U.label(hdr, subtitle, 13, color=T.TEXT_2).pack(anchor="w", pady=(4, 0))
        self.pages[key] = p
        return p

    def _metric(self, master, label, value="", sub=""):
        ctk, T, U = self.ctk, self.T, self.U
        c = U.card(master)
        i = ctk.CTkFrame(c, fg_color="transparent")
        i.pack(fill="both", expand=True, padx=18, pady=14)
        U.label(i, label.upper(), 10, color=T.TEXT_3, mono=True).pack(anchor="w")
        c.value = U.label(i, value, 22)
        c.value.pack(anchor="w", pady=(6, 0))
        c.sub = U.label(i, sub, 11, color=T.TEXT_3, mono=True)
        c.sub.pack(anchor="w")
        return c

    def _setting_row(self, master, title, desc, first=False):
        ctk, T, U = self.ctk, self.T, self.U
        if not first:
            U.hairline(master, fill="x", padx=18)
        r = ctk.CTkFrame(master, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=12)
        t = ctk.CTkFrame(r, fg_color="transparent")
        t.pack(side="left", fill="x", expand=True)
        U.label(t, title, 13, "medium").pack(anchor="w")
        if desc:
            r.desc = U.label(t, desc, 12, color=T.TEXT_2, wraplength=430, justify="left")
            r.desc.pack(anchor="w", pady=(1, 0))
        r.right = ctk.CTkFrame(r, fg_color="transparent")
        r.right.pack(side="right")
        return r

    # ================================================================ strona: Połącz
    def _build_connect_page(self):
        ctk, T, U = self.ctk, self.T, self.U
        p = self._page("connect", "Połącz", "Wpisz ID lub adres IP komputera. Hasło jest opcjonalne.")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=40, pady=(18, 0))
        row.grid_columnconfigure(0, weight=3)
        row.grid_columnconfigure(1, weight=2)

        f = U.card(row)
        f.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        inner = ctk.CTkFrame(f, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=22, pady=20)
        U.label(inner, "ADRES LUB ID", 10, color=T.TEXT_3, mono=True).pack(anchor="w")
        self.target = U.entry(inner, "123 456 789  ·  192.168.1.20", size=17, mono=True, height=44)
        self.target.pack(fill="x", pady=(6, 14))
        self.target.bind("<Return>", lambda e: self.connect())
        hr = ctk.CTkFrame(inner, fg_color="transparent")
        hr.pack(fill="x")
        U.label(hr, "HASŁO", 10, color=T.TEXT_3, mono=True).pack(side="left")
        U.label(hr, "opcjonalne", 11, color=T.TEXT_3).pack(side="right")
        pw_row = ctk.CTkFrame(inner, fg_color="transparent")
        pw_row.pack(fill="x", pady=(6, 6))
        self.pw = U.entry(pw_row, "hasło komputera zdalnego", show="•", height=38)
        self.pw.pack(side="left", fill="x", expand=True)
        self.pw.bind("<Return>", lambda e: self.connect())
        self.pw_shown = False
        self.eye = U.icon_button(pw_row, "eye", self._toggle_pw, tip="Pokaż / ukryj", width=38, height=38)
        self.eye.pack(side="left", padx=(6, 0))
        U.label(inner, "Bez hasła komputer zdalny wyświetli prośbę „Akceptuj / Odrzuć”.", 12, color=T.TEXT_3).pack(anchor="w")
        bot = ctk.CTkFrame(inner, fg_color="transparent")
        bot.pack(fill="x", pady=(18, 0))
        self.remember = ctk.BooleanVar(value=True)
        U.checkbox(bot, "Zapamiętaj hasło", self.remember).pack(side="left")
        self.connect_btn = U.primary_button(bot, "Połącz", self.connect, width=112)
        self.connect_btn.pack(side="right")
        self.conn_status = U.label(inner, "", 12, color=T.TEXT_2, wraplength=460, justify="left")
        self.conn_status.pack(anchor="w", pady=(10, 0))

        h = U.card(row)
        h.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        hi = ctk.CTkFrame(h, fg_color="transparent")
        hi.pack(fill="both", expand=True, padx=22, pady=20)
        U.label(hi, "TEN KOMPUTER", 10, color=T.TEXT_3, mono=True).pack(anchor="w")
        idr = ctk.CTkFrame(hi, fg_color="transparent")
        idr.pack(fill="x", pady=(8, 0))
        self.c_id = U.label(idr, format_id(self.hcfg["host_id"]), 24, mono=True)
        self.c_id.pack(side="left")
        U.icon_button(idr, "copy", self.copy_id, tip="Kopiuj ID").pack(side="left", padx=6)
        self.c_addr = U.label(hi, "", 11, color=T.TEXT_3, mono=True, wraplength=300, justify="left")
        self.c_addr.pack(anchor="w", pady=(2, 0))
        U.hairline(hi, fill="x", pady=16)
        sw = ctk.CTkFrame(hi, fg_color="transparent")
        sw.pack(fill="x")
        U.label(sw, "Zdalny dostęp", 13, "medium").pack(side="left")
        self.c_share_var = ctk.BooleanVar(value=False)
        U.switch(sw, "", self.c_share_var, command=lambda: self.toggle_share(self.c_share_var)).pack(side="right")
        self.c_state = U.label(hi, "", 12, color=T.TEXT_2)
        self.c_state.pack(anchor="w", pady=(4, 0))

        U.section(p, "ostatnie", padx=40, pady=(28, 10))
        self.recent = U.card(p)
        self.recent.pack(fill="x", padx=40, pady=(0, 34))
        self._fill_recent()

    def _toggle_pw(self):
        self.pw_shown = not self.pw_shown
        self.pw.configure(show="" if self.pw_shown else "•")
        self.eye.configure(image=self.T.icon("eye_off" if self.pw_shown else "eye", 16))

    def _computer_row(self, master, e, first):
        ctk, T, U = self.ctk, self.T, self.U
        if not first:
            U.hairline(master, fill="x", padx=16)
        r = ctk.CTkFrame(master, fg_color="transparent", height=58)
        r.pack(fill="x", padx=16)
        r.pack_propagate(False)
        box = ctk.CTkFrame(r, fg_color=T.SURFACE_2, corner_radius=8, width=34, height=34, border_width=1,
                           border_color=T.BORDER)
        box.pack(side="left")
        box.pack_propagate(False)
        ctk.CTkLabel(box, text="", image=T.icon("laptop" if "laptop" in e.get("name", "").lower() else "monitor", 16)).pack(expand=True)
        txt = ctk.CTkFrame(r, fg_color="transparent")
        txt.pack(side="left", padx=12, fill="x", expand=True)
        U.label(txt, (e.get("name") or e["addr"])[:34], 13, "medium").pack(anchor="w", pady=(9, 0))
        meta = [e["addr"]] + ([e["os"]] if e.get("os") else []) + ([ago(e.get("last"))] if e.get("last") else [])
        U.label(txt, "  ·  ".join(meta), 11, color=T.TEXT_3, mono=True).pack(anchor="w")
        more = U.icon_button(r, "more", lambda: None, tip="Więcej", width=30, height=30)
        more.configure(command=lambda: self._book_menu(e, more))
        more.pack(side="right")
        U.secondary_button(r, "Połącz", lambda: self.quick_connect(e), height=28, width=76).pack(side="right", padx=8)
        if e.get("key"):
            k = ctk.CTkLabel(r, text="", image=T.icon("key", 14, T.TEXT_3))
            k.pack(side="right", padx=4)
            U.Tooltip(k, "Hasło zapamiętane")

    def _fill_recent(self):
        for w in self.recent.winfo_children():
            w.destroy()
        book = self.cfg.get("book", [])[:5]
        if not book:
            self.U.label(self.recent, "Tu pojawią się komputery, z którymi się połączysz.", 12,
                         color=self.T.TEXT_3).pack(anchor="w", padx=18, pady=16)
            return
        for i, e in enumerate(book):
            self._computer_row(self.recent, e, i == 0)

    # ================================================================ strona: Komputery
    def _build_computers_page(self):
        ctk, T, U = self.ctk, self.T, self.U
        p = self._page("computers", "Komputery", "Zapisane komputery, hasła i Wake-on-LAN.")
        bar = ctk.CTkFrame(p, fg_color="transparent")
        bar.pack(fill="x", padx=40, pady=(18, 12))
        self.search = U.entry(bar, "Szukaj…", height=34, width=300)
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", lambda e: self._fill_book())
        U.secondary_button(bar, "Dodaj", self._add_computer, icon="plus", width=86).pack(side="right")
        self.book_list = U.card(p)
        self.book_list.pack(fill="x", padx=40, pady=(0, 34))
        self._fill_book()

    def _fill_book(self):
        for w in self.book_list.winfo_children():
            w.destroy()
        q = self.search.get().strip().lower() if hasattr(self, "search") else ""
        items = [e for e in self.cfg.get("book", []) if not q or q in (e.get("name", "") + " " + e["addr"]).lower()]
        self.nav["computers"].set_badge(str(len(self.cfg.get("book", []))) if self.cfg.get("book") else "")
        if not items:
            box = self.ctk.CTkFrame(self.book_list, fg_color="transparent")
            box.pack(pady=34)
            self.U.label(box, "Nic nie znaleziono" if q else "Brak zapisanych komputerów", 14, "medium").pack()
            self.U.label(box, "Połącz się raz z komputerem – zapisze się tutaj.", 12, color=self.T.TEXT_3).pack(pady=(4, 0))
            return
        for i, e in enumerate(items):
            self._computer_row(self.book_list, e, i == 0)

    def _refresh_book_views(self):
        save_config(self.cfg)
        self._fill_book()
        self._fill_recent()

    def _book_menu(self, e, widget):
        items = [("Połącz", lambda: self.quick_connect(e)),
                 ("Obudź (Wake-on-LAN)", lambda: self.wake(e)),
                 None,
                 ("Zmień nazwę", lambda: self._book_rename(e))]
        if e.get("key"):
            items.append(("Zapomnij hasło", lambda: self._book_forget(e)))
        items += [None, ("Usuń z listy", lambda: self._book_delete(e))]
        self.U.popup_menu(widget, items)

    def _book_rename(self, e):
        n = self.U.ask_string(self.root, "Zmień nazwę", "Nazwa komputera:", e.get("name", ""))
        if n:
            e["name"] = n
            e["custom_name"] = True
            self._refresh_book_views()

    def _book_forget(self, e):
        e.pop("key", None)
        e.pop("salt", None)
        self._refresh_book_views()
        self.toast("Zapomniano hasło.")

    def _book_delete(self, e):
        if self.U.confirm(self.root, "Usunąć z listy?", e.get("name") or e["addr"], "Usuń", danger=True, icon="trash"):
            self.cfg["book"].remove(e)
            self._refresh_book_views()

    def _add_computer(self):
        addr = self.U.ask_string(self.root, "Dodaj komputer", "ID lub adres IP:", icon="plus")
        if addr:
            if not self._book_entry(addr):
                self.cfg.setdefault("book", []).insert(0, {"addr": addr, "name": addr})
                self._refresh_book_views()
            self.show_page("connect")
            self._set_target(addr)
            self.pw.focus_set()

    def _book_entry(self, addr):
        norm = addr.replace(" ", "")
        for e in self.cfg.get("book", []):
            if e["addr"].replace(" ", "") == norm:
                return e
        return None

    def wake(self, e):
        mac = e.get("mac")
        if not mac:
            self.toast("Brak adresu MAC – połącz się raz z tym komputerem, gdy jest włączony.", "warn")
            return
        sent = []
        try:
            send_wol(mac)
            sent.append("z tego komputera")
        except Exception as ex:
            self.toast(f"Wake-on-LAN: {ex}", "error")
        if self.sessions_win:  # przez inne komputery, z którymi jest połączenie (np. w tej samej sieci domowej)
            for v in self.sessions_win.views:
                if v.conn["target"] != e["addr"] and v.ch:
                    v.send_json({"t": "wol", "req": 0, "mac": mac})
                    sent.append(f"przez {v.remote_name}")
        self.toast(f"Wysłano sygnał wybudzenia ({', '.join(sent)}). Spróbuj połączyć się za ~30 s.", "ok", 6000)

    # ================================================================ strona: Dostęp
    def _build_access_page(self):
        ctk, T, U = self.ctk, self.T, self.U
        p = self._page("access", "Dostęp", "Kto i jak może łączyć się z tym komputerem.")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=40, pady=(18, 0))
        row.grid_columnconfigure((0, 1, 2), weight=1, uniform="m")
        self.m_sess = self._metric(row, "sesje", "0", "nikt nie jest połączony")
        self.m_sess.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.m_direct = self._metric(row, "bezpośrednio", "—", "LAN / VPN / port")
        self.m_direct.grid(row=0, column=1, sticky="nsew", padx=6)
        self.m_relay = self._metric(row, "serwer id", "—", "łączenie po ID")
        self.m_relay.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        U.section(p, "ustawienia", padx=40)
        c = U.card(p)
        c.pack(fill="x", padx=40)
        r = self._setting_row(c, "Zdalny dostęp", "Pozwól łączyć się z tym komputerem.", first=True)
        self.a_share_var = ctk.BooleanVar(value=False)
        U.switch(r.right, "", self.a_share_var, command=lambda: self.toggle_share(self.a_share_var)).pack()
        self.r_pw = self._setting_row(c, "Hasło", "…")
        U.secondary_button(self.r_pw.right, "Zmień hasło", self.set_password_dialog, width=120).pack()
        r = self._setting_row(c, "Połączenia bez hasła",
                              "Ktoś może poprosić o dostęp – połączy się dopiero, gdy klikniesz „Akceptuj”.")
        self.a_ask_var = ctk.BooleanVar(value=bool(self.hcfg.get("ask_enabled", True)))
        U.switch(r.right, "", self.a_ask_var, command=self._toggle_ask).pack()
        self.r_svc = self._setting_row(c, "Usługa systemowa",
                                       "Dostęp do ekranu logowania, okien UAC i Ctrl+Alt+Del – także po restarcie, "
                                       "zanim ktoś się zaloguje. Wymaga uprawnień administratora.")
        self.svc_btn = U.secondary_button(self.r_svc.right, "Zainstaluj", self._toggle_service, width=120)
        self.svc_btn.pack()

        U.section(p, "aktywne sesje", padx=40)
        self.h_sessions = U.card(p)
        self.h_sessions.pack(fill="x", padx=40)
        U.section(p, "dziennik", padx=40)
        self.log_box = ctk.CTkTextbox(p, height=170, font=T.font(11, mono=True), fg_color=T.SURFACE,
                                      border_color=T.BORDER, border_width=1, corner_radius=12, text_color=T.TEXT_2)
        self.log_box.pack(fill="x", padx=40, pady=(0, 34))
        self.log_box.configure(state="disabled")

    # ================================================================ strona: Ustawienia
    def _build_settings_page(self):
        ctk, T, U = self.ctk, self.T, self.U
        p = self._page("settings", "Ustawienia", "Sieć, uruchamianie, aktualizacje i wygląd.")

        U.section(p, "sieć", padx=40, pady=(22, 10))
        c = U.card(p)
        c.pack(fill="x", padx=40)
        r = self._setting_row(c, "Serwer pośredniczący", "Adres serwera z pd_relay.py – łączenie po ID przez internet.", first=True)
        self.s_relay = U.entry(r.right, "serwer.pl:47900", width=240, height=34, mono=True, size=12)
        self.s_relay.pack()
        self.s_relay.insert(0, self.hcfg.get("relay", ""))
        r = self._setting_row(c, "Klucz serwera", "Jeśli serwer został uruchomiony z --key.")
        self.s_rkey = U.entry(r.right, "", show="•", width=240, height=34)
        self.s_rkey.pack()
        self.s_rkey.insert(0, self.hcfg.get("relay_key", ""))
        r = self._setting_row(c, "Połączenia bezpośrednie", "Po adresie IP: sieć lokalna, Tailscale, przekierowany port.")
        self.s_direct = ctk.BooleanVar(value=self.hcfg.get("direct_enabled", True))
        self.s_port = U.entry(r.right, "", width=80, height=34, mono=True, size=12)
        self.s_port.pack(side="right", padx=(10, 0))
        self.s_port.insert(0, str(self.hcfg.get("listen_port", DEFAULT_PORT)))
        U.switch(r.right, "", self.s_direct).pack(side="right")

        U.section(p, "uruchamianie", padx=40)
        c = U.card(p)
        c.pack(fill="x", padx=40)
        r = self._setting_row(c, "Start razem z systemem", "PilotDesk działa w tle po zalogowaniu.", first=True)
        self.s_auto = ctk.BooleanVar(value=self._autostart_enabled())
        U.switch(r.right, "", self.s_auto).pack()

        U.section(p, "aktualizacje", padx=40)
        c = U.card(p)
        c.pack(fill="x", padx=40)
        r = self._setting_row(c, "Źródło", "Repozytorium GitHub „właściciel/nazwa” (zakładka Releases) albo adres "
                                         "URL pliku JSON z opisem wersji.", first=True)
        self.s_upd = U.entry(r.right, "uzytkownik/pilotdesk", width=240, height=34, mono=True, size=12)
        self.s_upd.pack()
        self.s_upd.insert(0, update_source(self.cfg))
        r = self._setting_row(c, "Aktualizuj automatycznie", "Nowa wersja instaluje się sama, gdy nie trwa żadna sesja.")
        self.s_auto_upd = ctk.BooleanVar(value=self.cfg.get("auto_update", True))
        U.switch(r.right, "", self.s_auto_upd).pack()
        r = self._setting_row(c, f"Wersja {VERSION}", "")
        self.upd_status = r.desc if hasattr(r, "desc") else None
        self.upd_state = U.label(r.right, "", 12, color=T.TEXT_2)
        self.upd_state.pack(side="left", padx=10)
        U.secondary_button(r.right, "Sprawdź teraz", lambda: self.check_updates(manual=True), width=120).pack(side="left")

        U.section(p, "wygląd", padx=40)
        c = U.card(p)
        c.pack(fill="x", padx=40)
        r = self._setting_row(c, "Motyw", "", first=True)
        self.s_theme = ctk.StringVar(value={"dark": "Ciemny", "light": "Jasny", "system": "Systemowy"}[self.cfg.get("theme", "dark")])
        ctk.CTkSegmentedButton(r.right, values=["Ciemny", "Jasny", "Systemowy"], variable=self.s_theme,
                               command=self._change_theme, font=T.font(12), height=30, corner_radius=8,
                               selected_color=T.SURFACE_3, selected_hover_color=T.SURFACE_3,
                               unselected_color=T.SURFACE_2, unselected_hover_color=T.SURFACE_3,
                               text_color=T.TEXT, fg_color=T.SURFACE_2).pack()

        U.section(p, "instalacja", padx=40)
        c = U.card(p)
        c.pack(fill="x", padx=40)
        r = self._setting_row(c, "Skrót na pulpicie", "", first=True)
        U.secondary_button(r.right, "Utwórz", self._make_shortcut, width=100).pack()
        if INST.running_installed():
            r = self._setting_row(c, "Odinstaluj PilotDesk", "Usuwa program, skróty, autostart i usługę.")
            U.danger_button(r.right, "Odinstaluj", self._uninstall, width=110).pack()
        r = self._setting_row(c, "Pliki ustawień", config_path() + ("\n" + self.hpath if self.hpath else ""))

        bar = ctk.CTkFrame(p, fg_color="transparent")
        bar.pack(fill="x", padx=40, pady=(18, 34))
        U.primary_button(bar, "Zapisz", self.save_settings, width=110).pack(side="right")

    def _autostart_enabled(self):
        try:
            return INST.autostart_enabled()
        except Exception:
            return False

    def _change_theme(self, val):
        mode = {"Ciemny": "dark", "Jasny": "light", "Systemowy": "system"}[val]
        self.cfg["theme"] = mode
        save_config(self.cfg)
        self.ctk.set_appearance_mode(mode)
        self.T.apply_dark_title_bar(self.root, self.ctk.get_appearance_mode() == "Dark")

    def save_settings(self):
        try:
            port = int(self.s_port.get())
            assert 1 <= port <= 65535
        except Exception:
            self.toast("Nieprawidłowy numer portu.", "error")
            return
        self.hcfg["relay"] = self.s_relay.get().strip()
        self.hcfg["relay_key"] = self.s_rkey.get().strip()
        self.hcfg["listen_port"] = port
        self.hcfg["direct_enabled"] = bool(self.s_direct.get())
        self.cfg["update_source"] = self.s_upd.get().strip()
        self.cfg["auto_update"] = bool(self.s_auto_upd.get())
        self.hcfg["update_source"] = self.cfg["update_source"]
        self.hcfg["auto_update"] = self.cfg["auto_update"]
        save_config(self.cfg)
        self._save_host()
        try:
            INST.set_autostart(bool(self.s_auto.get()))
        except Exception as e:
            self.toast(f"Autostart: {e}", "error")
        if self.host and not self.service:
            self.start_host()
        self._refresh_host()
        self.toast("Zapisano.", "ok")

    def _make_shortcut(self):
        try:
            INST.create_desktop_shortcut()
            self.toast("Utworzono skrót na pulpicie.", "ok")
        except Exception as e:
            self.toast(f"Nie udało się utworzyć skrótu: {e}", "error")

    def _uninstall(self):
        r = self.U.confirm(self.root, "Odinstalować PilotDesk?", "Program, skróty, autostart i usługa zostaną usunięte.",
                           "Odinstaluj", danger=True, icon="trash", check="Usuń też ustawienia i zapisane komputery")
        if r:
            if self.service:
                self._run_service_admin("--uninstall-service")
            if self.host:
                self.host.stop()
            INST.uninstall(remove_settings=r[1])
            self.quit()

    # ================================================================ usługa systemowa
    def _run_service_admin(self, arg):
        import pd_winutil as W
        if not (INST.is_windows() and INST.is_frozen()):
            self.toast("Usługa systemowa jest dostępna w wersji PilotDesk.exe dla Windows.", "warn")
            return None
        try:
            extra = f' "{config_path()}"' if arg == "--install-service" else ""
            return W.run_elevated(sys.executable, arg + extra, wait=True)
        except OSError as e:
            self.toast(str(e), "error")
            return None

    def _toggle_service(self):
        if not self.service:
            if not (has_password(self.hcfg) or self.hcfg.get("ask_enabled", True)):
                self.toast("Najpierw ustaw hasło.", "warn")
                return
            if not self.U.confirm(self.root, "Zainstalować usługę?",
                                  "PilotDesk będzie działał jako usługa Windows: dostęp do ekranu logowania i okien UAC, "
                                  "także po restarcie. Windows poprosi o zgodę administratora.", "Zainstaluj", icon="shield"):
                return
            if self.host:
                self.host.stop()
                self.host = None
            code = self._run_service_admin("--install-service")
            if code == 0:
                self.toast("Usługa zainstalowana.", "ok")
        else:
            if not self.U.confirm(self.root, "Odinstalować usługę?", "Wrócisz do zwykłego trybu (dostęp tylko po zalogowaniu).",
                                  "Odinstaluj", danger=True, icon="shield"):
                return
            for k in ("host_id", "id_secret", "pw_salt", "pw_key", "relay", "relay_key", "listen_port",
                      "direct_enabled", "ask_enabled"):
                if k in self.hcfg:
                    self.cfg[k] = self.hcfg[k]
            self.cfg["host_enabled"] = True
            save_config(self.cfg)
            if self.host:
                self.host.stop()
                self.host = None
            code = self._run_service_admin("--uninstall-service")
            if code == 0:
                self.toast("Usługa usunięta.", "ok")
        self._load_host_cfg()
        self.start_host() if (self.service or self.hcfg.get("host_enabled")) else None
        self._refresh_host()

    # ================================================================ zdarzenia z wątków
    def post(self, kind, data=None):
        self.events.put((kind, data))

    def _poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                try:
                    self._handle_event(kind, data)
                except Exception as e:
                    print("PilotDesk:", kind, e, file=sys.stderr)
        except queue.Empty:
            pass
        if self.ext_queue:
            try:
                while True:
                    self._handle_event(self.ext_queue.get_nowait(), None)
            except queue.Empty:
                pass
        self.root.after(100, self._poll)

    def _handle_event(self, kind, data):
        if kind == "log":
            self.log_box.configure(state="normal")
            self.log_box.insert("end", data + "\n")
            if int(self.log_box.index("end").split(".")[0]) > 500:
                self.log_box.delete("1.0", "2.0")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        elif kind in ("status", "sessions"):
            self._refresh_host()
        elif kind == "chat":
            self._host_chat(*data)
        elif kind == "ask":
            client, peer, code, answer = data
            self.U.AskDialog(self.root, client, peer, code, answer)
        elif kind == "connected":
            self._on_connected(*data)
        elif kind == "conn_error":
            self._set_connecting(False)
            self.conn_status.configure(text=data, text_color=self.T.RED)
        elif kind == "conn_code":
            self.conn_status.configure(text=f"Czekam na akceptację na komputerze zdalnym.   Kod: {data[:3]} {data[3:]}",
                                       text_color=self.T.TEXT_2)
        elif kind == "update":
            self._on_update_info(*data)
        elif kind == "toast":
            self.toast(*data)
        elif kind == "show":
            self.show_window()
        elif kind == "quit":
            self.quit()

    def toast(self, text, kind="info", ms=3500):
        self.U.Toast(self.root, text, kind, ms)

    def copy_id(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.hcfg["host_id"])
        self.toast("Skopiowano ID.", "ok")

    # ================================================================ udostępnianie
    def ask_sync(self, client, peer, code):
        ev = threading.Event()
        res = [False]

        def answer(ok):
            res[0] = bool(ok)
            ev.set()
        self.post("ask", (client, peer, code, answer))
        ev.wait(60)
        return res[0]

    def start_host(self):
        if self.host:
            self.host.stop()
        log = lambda m: self.post("log", m)  # noqa: E731
        if self.service:
            from pd_service import ServiceHostProxy
            self.host = ServiceHostProxy(log, lambda s, t: self.post("chat", (s, t)), lambda: self.post("sessions"),
                                         lambda: self.post("status"), lambda c, p, code, a: self.post("ask", (c, p, code, a)))
            return
        from pd_host import HostService
        self.host = HostService(self.hcfg, log=lambda m: log(time.strftime("%H:%M:%S  ") + m),
                                on_chat=lambda s, t: self.post("chat", (s, t)), on_sessions=lambda: self.post("sessions"),
                                on_status=lambda: self.post("status"), ask=self.ask_sync)
        try:
            self.host.start()
        except Exception as e:
            log(f"Nie można uruchomić udostępniania: {e}")
            self.host = None

    def toggle_share(self, var):
        if self.service:
            var.set(True)
            self.toast("Dostępem zarządza usługa systemowa (Dostęp → Usługa systemowa).", "warn")
            return
        if var.get():
            if not has_password(self.hcfg) and not self.hcfg.get("ask_enabled", True) and not self.set_password_dialog():
                var.set(False)
                return
            self.hcfg["host_enabled"] = True
            self._save_host()
            self.start_host()
            self.toast("Zdalny dostęp włączony.", "ok")
        else:
            if self.host and self.host.sessions and not self.U.confirm(
                    self.root, "Wyłączyć dostęp?", "Ktoś jest teraz połączony.", "Wyłącz", danger=True):
                var.set(True)
                return
            self.hcfg["host_enabled"] = False
            self._save_host()
            if self.host:
                self.host.stop()
                self.host = None
            self.toast("Zdalny dostęp wyłączony.")
        self._refresh_host()

    def _toggle_ask(self):
        self.hcfg["ask_enabled"] = bool(self.a_ask_var.get())
        self._save_host()
        if self.host and not self.service:
            self.start_host()
        self._refresh_host()

    def set_password_dialog(self):
        p = self.U.ask_password(self.root)
        if not p:
            return False
        set_host_password(self.hcfg, p)
        self._save_host()
        self.post("log", time.strftime("%H:%M:%S  ") + "Ustawiono nowe hasło dostępu")
        if self.host and not self.service:
            self.start_host()
        self._refresh_host()
        self.toast("Hasło zapisane.", "ok")
        return True

    def _refresh_host(self):
        T, U = self.T, self.U
        port = self.hcfg.get("listen_port", DEFAULT_PORT)
        ips = get_local_ips()
        self.c_addr.configure(text="  ·  ".join(f"{ip}:{port}" for ip in ips[:2]))
        on = self.host is not None
        for v in (self.c_share_var, self.a_share_var):
            v.set(on)
        pw = has_password(self.hcfg)
        if on:
            mode = "usługa" if self.service else "aplikacja"
            state, color = f"Gotowy · {'hasło ustawione' if pw else 'tylko z akceptacją'} · {mode}", T.GREEN
        elif not pw and not self.hcfg.get("ask_enabled", True):
            state, color = "Ustaw hasło, aby włączyć dostęp", T.AMBER
        else:
            state, color = "Wyłączony", T.TEXT_3
        self.c_state.configure(text=("●  " + state), text_color=color if on else T.TEXT_2)
        self.me_dot.configure(image=T.icon("dot", 11, color if on else T.TEXT_3))
        self.me_sub.configure(text=f"ID {format_id(self.hcfg['host_id'])}")
        self.nav["access"].set_badge(dot=T.GREEN if on else T.TEXT_3)
        self.r_pw.desc.configure(text="Ustawione." if pw else "Brak – połączenia tylko z akceptacją (jeśli włączone).")
        self.a_ask_var.set(bool(self.hcfg.get("ask_enabled", True)))
        self.svc_btn.configure(text="Odinstaluj" if self.service else "Zainstaluj")
        sessions = list(self.host.sessions) if on else []
        self.m_sess.value.configure(text=str(len(sessions)))
        self.m_sess.sub.configure(text="połączonych teraz" if sessions else "nikt nie jest połączony")
        if on:
            d = self.host.direct_status
            self.m_direct.value.configure(text="aktywne" if "port" in d else d[:22], text_color=T.TEXT)
            self.m_direct.sub.configure(text=d[:34])
            rs = self.host.relay_status
            self.m_relay.value.configure(text="połączony" if rs.startswith("połączony") else
                                         ("brak" if "nie skonfig" in rs else "offline"))
            self.m_relay.sub.configure(text=rs[:34])
        else:
            for m in (self.m_direct, self.m_relay):
                m.value.configure(text="—")
        for w in self.h_sessions.winfo_children():
            w.destroy()
        if not sessions:
            U.label(self.h_sessions, "Nikt nie jest teraz połączony z tym komputerem.", 12, color=T.TEXT_3).pack(
                anchor="w", padx=18, pady=16)
        for i, s in enumerate(sessions):
            if i:
                U.hairline(self.h_sessions, fill="x", padx=16)
            r = self.ctk.CTkFrame(self.h_sessions, fg_color="transparent", height=52)
            r.pack(fill="x", padx=16)
            r.pack_propagate(False)
            U.dot(r, T.RED, 7).pack(side="left")
            t = self.ctk.CTkFrame(r, fg_color="transparent")
            t.pack(side="left", padx=10)
            U.label(t, s.client, 13, "medium").pack(anchor="w", pady=(7, 0))
            U.label(t, f"{s.peer}  ·  od {time.strftime('%H:%M', time.localtime(s.started))}", 11, color=T.TEXT_3, mono=True).pack(anchor="w")
            U.danger_button(r, "Rozłącz", s.stop, height=28, width=86).pack(side="right")
            U.secondary_button(r, "Czat", lambda s=s: self._host_chat(s, None), height=28, width=66).pack(side="right", padx=8)
        self._update_banner(sessions)
        self._update_tray()

    def _update_banner(self, sessions):
        from pd_viewer import ConnectedBanner
        if sessions:
            if not self.banner or not self.banner.winfo_exists():
                self.banner = ConnectedBanner(self.root, on_disconnect=lambda: self.host and self.host.disconnect_all(),
                                              on_chat=lambda: self.host and self.host.sessions and
                                              self._host_chat(next(iter(self.host.sessions)), None))
            self.banner.set_sessions([s.client for s in sessions])
        elif self.banner and self.banner.winfo_exists():
            self.banner.destroy()
            self.banner = None

    def _host_chat(self, sess, text):
        from pd_viewer import ChatWindow
        w = self.host_chats.get(sess)
        if not w or not w.winfo_exists():
            w = ChatWindow(self.root, sess.client, on_send=sess.send_chat)
            w.attributes("-topmost", True)
            self.host_chats[sess] = w
        w.deiconify()
        w.lift()
        if text is not None:
            w.add(sess.client, text, mine=False)

    # ================================================================ łączenie
    def _set_target(self, addr):
        self.target.delete(0, "end")
        self.target.insert(0, addr)

    def quick_connect(self, e):
        self.show_page("connect")
        self._set_target(e["addr"])
        self.pw.delete(0, "end")
        if e.get("key"):
            self.connect()
        else:
            self.conn_status.configure(text="Wpisz hasło (albo zostaw puste, aby poprosić o akceptację) i kliknij „Połącz”.",
                                       text_color=self.T.TEXT_2)
            self.pw.focus_set()

    def _set_connecting(self, on):
        self.connecting = on
        self.connect_btn.configure(state="disabled" if on else "normal", text="Łączenie…" if on else "Połącz")

    def open_connection(self, target, password="", mode=None, saved=None, on_code=None):
        """Nawiązuje połączenie (blokuje – wołać z wątku). Zwraca (kanał, hello, ok, klucz_hasła)."""
        from pd_viewer import viewer_caps
        saved = saved or {}
        if mode is None:
            mode = "password" if (password or saved.get("key")) else "ask"
        kind = parse_target(target)
        if kind[0] == "id":
            relay = self.hcfg.get("relay", "")
            if not relay:
                raise ConnectionError("Aby łączyć się po ID, ustaw serwer pośredniczący w Ustawieniach (albo wpisz adres IP).")
            sock = relay_connect_viewer(relay, self.hcfg.get("relay_key", ""), kind[1])
        else:
            sock = open_tcp(kind[1], kind[2])
        try:
            sock.settimeout(30)

            def key_provider(salt):
                if not password and saved.get("key") and saved.get("salt") == b64e(salt):
                    return b64d(saved["key"])
                if not password:
                    raise AuthError("Komputer zdalny zmienił hasło – wpisz je ponownie.")
                return derive_password_key(password, salt)

            ch, hello, ok, pw_key = viewer_handshake(sock, key_provider, {"client": f"{username()}@{hostname()}",
                                                                          "caps": viewer_caps()}, mode=mode, on_code=on_code)
            sock.settimeout(60)
            return ch, hello, ok, pw_key
        except Exception:
            sock.close()
            raise

    def connect(self):
        if self.connecting:
            return
        target = self.target.get().strip()
        if not target:
            self.conn_status.configure(text="Wpisz ID lub adres komputera.", text_color=self.T.AMBER)
            self.target.focus_set()
            return
        password = self.pw.get()
        saved = self._book_entry(target) or {}
        self._set_connecting(True)
        self.conn_status.configure(text=f"Łączenie z {target}…", text_color=self.T.TEXT_2)
        threading.Thread(target=self._connect_thread, args=(target, password, bool(self.remember.get()), saved),
                         daemon=True).start()

    def _connect_thread(self, target, password, remember, saved):
        try:
            ch, hello, ok, pw_key = self.open_connection(target, password, saved=saved,
                                                         on_code=lambda c: self.post("conn_code", c))
            self.post("connected", (target, ch, hello, ok, pw_key, hello["salt"], remember))
        except Exception as e:
            msg = str(e) or e.__class__.__name__
            if isinstance(e, ConnectionRefusedError):
                msg = "Komputer nie odpowiada (wyłączony, dostęp wyłączony albo zablokowany port)."
            elif isinstance(e, TimeoutError) or e.__class__.__name__ == "timeout":
                msg = "Przekroczono czas oczekiwania."
            elif isinstance(e, OSError) and not isinstance(e, ConnectionError):
                msg = f"Nie można połączyć: {e.strerror or e}"
            self.post("conn_error", msg)

    def _on_connected(self, target, ch, hello, ok, pw_key, salt_b64, remember):
        from pd_viewer import SessionsWindow
        self._set_connecting(False)
        name = ok.get("name") or hello.get("name") or target
        self.conn_status.configure(text=f"Połączono z {name}.", text_color=self.T.GREEN)
        e = self._book_entry(target)
        if not e:
            e = {"addr": target}
            self.cfg.setdefault("book", []).insert(0, e)
        else:
            self.cfg["book"].remove(e)
            self.cfg["book"].insert(0, e)
        if not e.get("custom_name"):
            e["name"] = name
        e["os"] = ok.get("os", e.get("os", ""))
        e["last"] = time.time()
        if ok.get("mac"):
            e["mac"] = ok["mac"]
        if pw_key and remember:
            e["salt"], e["key"] = salt_b64, b64e(pw_key)
        elif not remember:
            e.pop("key", None)
            e.pop("salt", None)
        self._refresh_book_views()
        self.pw.delete(0, "end")
        conn = {"target": target, "name": e.get("name", name), "custom": e.get("name") if e.get("custom_name") else None,
                "mode": "password" if pw_key else "ask", "salt": salt_b64, "pw_key": b64e(pw_key) if pw_key else None}
        if not self.sessions_win or not self.sessions_win.winfo_exists():
            self.sessions_win = SessionsWindow(self)
        self.sessions_win.add(conn, ch, hello, ok)

    def on_session_attached(self, view, ok):
        e = self._book_entry(view.conn["target"])
        if e and ok.get("mac") and e.get("mac") != ok["mac"]:
            e["mac"] = ok["mac"]
            save_config(self.cfg)

    # ================================================================ aktualizacje
    def check_updates(self, manual=False):
        src = (self.s_upd.get().strip() if manual else update_source(self.cfg)).strip()
        if not src:
            if manual:
                self.toast("Wpisz źródło aktualizacji (repozytorium GitHub albo URL).", "warn")
            return
        if manual:
            self.upd_state.configure(text="sprawdzam…")

        def work():
            import pd_update
            try:
                info = pd_update.check(src)
                self.post("update", (info, manual, None))
            except Exception as e:
                self.post("update", (None, manual, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _on_update_info(self, info, manual, err):
        import pd_update
        if err:
            self.upd_state.configure(text="błąd sprawdzania")
            if manual:
                self.toast(f"Aktualizacje: {err}", "error", 6000)
            return
        if not info or not pd_update.newer(info["version"], VERSION):
            self.upd_state.configure(text="masz najnowszą wersję")
            return
        self.update_info = info
        self.upd_state.configure(text=f"dostępna {info['version']}")
        self.update_btn.configure(text=f"Aktualizuj do {info['version']}")
        self.update_btn.pack(side="bottom", fill="x", padx=12, pady=(0, 4))
        busy = (self.host and self.host.sessions) or (self.sessions_win and self.sessions_win.views)
        if (self.cfg.get("auto_update", True) and not manual and not busy) or manual:
            self._install_update_now()

    def _install_update_now(self):
        if not self.update_info:
            return
        if not (INST.is_frozen() and INST.is_windows()):
            self.toast("Automatyczna instalacja działa w wersji PilotDesk.exe. Pobierz nową wersję ręcznie.", "warn", 6000)
            return
        info = self.update_info
        self.toast(f"Pobieranie wersji {info['version']}…")

        def work():
            import pd_update
            try:
                path = pd_update.download(info)
                INST.launch_detached([path, "--apply-update"])
                self.post("quit")
            except Exception as e:
                self.post("toast", (f"Aktualizacja nieudana: {e}", "error", 6000))
        threading.Thread(target=work, daemon=True).start()

    def _auto_update_tick(self):
        if self.cfg.get("auto_update", True) and update_source(self.cfg):
            self.check_updates(manual=False)
        self.root.after(12 * 3600 * 1000, self._auto_update_tick)

    # ================================================================ zasobnik i zamykanie
    def _setup_tray(self):
        if sys.platform != "win32":
            return
        try:
            import pystray
            self.tray = pystray.Icon(
                "PilotDesk", self.T.logo(64), "PilotDesk",
                pystray.Menu(
                    pystray.MenuItem("Otwórz PilotDesk", lambda: self.post("show"), default=True),
                    pystray.MenuItem(lambda _i: f"ID: {format_id(self.hcfg['host_id'])}", None, enabled=False),
                    pystray.MenuItem(lambda _i: "Dostęp: włączony" if self.host else "Dostęp: wyłączony", None, enabled=False),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Zakończ", lambda: self.post("quit")),
                ))
            self.tray.run_detached()
        except Exception:
            self.tray = None

    def _update_tray(self):
        if self.tray:
            try:
                n = len(self.host.sessions) if self.host else 0
                self.tray.title = f"PilotDesk – połączonych: {n}" if n else "PilotDesk"
                self.tray.update_menu()
            except Exception:
                pass

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_close(self):
        if self.tray:
            self.root.withdraw()
            if not self.tray_notified:
                self.tray_notified = True
                try:
                    self.tray.notify("PilotDesk działa w tle. Kliknij ikonę przy zegarze, aby otworzyć.", "PilotDesk")
                except Exception:
                    pass
            return
        if self.host and not self.service:
            if not self.U.confirm(self.root, "Zamknąć PilotDesk?", "Zdalny dostęp do tego komputera zostanie wyłączony.",
                                  "Zamknij", danger=True, icon="power", cancel_text="Minimalizuj"):
                self.root.iconify()
                return
        self.quit()

    def quit(self):
        if self.host:
            self.host.stop()
        if self.sessions_win:
            for v in list(self.sessions_win.views):
                v.close()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()


# --------------------------------------------------------------------------- instalator (Windows, .exe)

class InstallWindow:
    def __init__(self, root):
        import customtkinter as ctk
        import pd_theme as T
        import pd_ui as U
        self.root, self.ctk, self.T, self.U = root, ctk, T, U
        self.result = None
        update = INST.is_installed()
        root.title("PilotDesk")
        root.geometry("460x520")
        root.resizable(False, False)
        root.configure(fg_color=T.BG)
        T.apply_window_icon(root)
        T.apply_dark_title_bar(root, ctk.get_appearance_mode() == "Dark")
        f = ctk.CTkFrame(root, fg_color="transparent")
        f.pack(fill="both", expand=True, padx=36, pady=32)
        ctk.CTkLabel(f, text="", image=T.ctk_logo(64)).pack(anchor="w")
        U.label(f, "PilotDesk", 24, "bold").pack(anchor="w", pady=(16, 0))
        U.label(f, f"Aktualizacja do wersji {VERSION}" if update else "Zdalny pulpit do Twoich komputerów.", 13,
                color=T.TEXT_2).pack(anchor="w")
        U.section(f, "instalacja", pady=(24, 8))
        self.v_desk = ctk.BooleanVar(value=True)
        self.v_start = ctk.BooleanVar(value=True)
        self.v_auto = ctk.BooleanVar(value=True)
        for text, var in (("Skrót na pulpicie", self.v_desk), ("Skrót w menu Start", self.v_start),
                          ("Uruchamiaj razem z Windows", self.v_auto)):
            U.checkbox(f, text, var).pack(anchor="w", pady=5)
        self.status = U.label(f, "", 12, color=T.TEXT_2)
        self.status.pack(anchor="w", pady=(14, 0))
        b = ctk.CTkFrame(f, fg_color="transparent")
        b.pack(side="bottom", fill="x")
        self.btn = U.primary_button(b, "Zaktualizuj" if update else "Zainstaluj", self.do_install, height=40)
        self.btn.pack(fill="x")
        U.secondary_button(b, "Uruchom bez instalowania", self.run_portable, height=36).pack(fill="x", pady=(8, 0))
        root.protocol("WM_DELETE_WINDOW", root.destroy)

    def do_install(self):
        self.btn.configure(state="disabled", text="Instalowanie…")

        def work():
            try:
                exe = INST.install(self.v_desk.get(), self.v_start.get(), self.v_auto.get(), VERSION,
                                   log=lambda m: self.root.after(0, lambda: self.status.configure(text=m)))
                self.root.after(0, lambda: self._done(exe))
            except Exception as e:
                self.root.after(0, lambda: self._fail(e))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, exe):
        self.status.configure(text="Gotowe – uruchamiam PilotDesk…", text_color=self.T.GREEN)
        INST.launch_detached([exe])
        self.root.after(900, self.root.destroy)

    def _fail(self, e):
        self.btn.configure(state="normal", text="Spróbuj ponownie")
        self.status.configure(text=f"Błąd instalacji: {e}", text_color=self.T.RED)

    def run_portable(self):
        self.result = "portable"
        self.root.destroy()


def run_uninstall_gui():
    import customtkinter as ctk
    import pd_ui as U
    cfg = load_config()
    init_ctk(cfg)
    root = ctk.CTk()
    root.withdraw()
    r = U.confirm(root, "Odinstalować PilotDesk?", "Program, skróty, autostart i usługa zostaną usunięte.",
                  "Odinstaluj", danger=True, icon="trash", check="Usuń też ustawienia i zapisane komputery")
    if r:
        try:
            import pd_service
            if pd_service.service_installed():
                import pd_winutil as W
                W.run_elevated(sys.executable, "--uninstall-service", wait=True)
        except Exception:
            pass
        INST.uninstall(remove_settings=r[1])
        U.info(root, "Odinstalowano", "PilotDesk został usunięty.", icon="check")
    root.destroy()


def run_gui(cfg, minimized):
    import customtkinter as ctk
    init_ctk(cfg)
    if INST.should_offer_install() and not minimized:
        root = ctk.CTk()
        w = InstallWindow(root)
        root.mainloop()
        if w.result != "portable":
            return
    ext = queue.Queue()
    si = INST.SingleInstance(ext.put)
    if not si.acquire():
        INST.send_to_instance("show")
        return
    root = ctk.CTk()
    App(root, cfg, ext_queue=ext, minimized=minimized)
    root.mainloop()


def main():
    if sys.stdout is None:  # wersja .exe bez konsoli – print() nie może się wywracać
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    argv = sys.argv[1:]
    # tryby wewnętrzne (usługa Windows, agent, instalacja z uprawnieniami administratora, aktualizacje)
    if argv[:1] == ["--service"]:
        import pd_service
        pd_service.run_service_dispatcher()
        return
    if argv[:1] == ["--agent"]:
        import pd_service
        pd_service.run_agent()
        return
    if argv[:1] == ["--install-service"]:
        import pd_service
        sys.exit(pd_service.install_service(argv[1] if len(argv) > 1 else ""))
    if argv[:1] == ["--uninstall-service"]:
        import pd_service
        sys.exit(pd_service.uninstall_service())
    if argv[:1] == ["--service-update"]:
        import pd_service
        sys.exit(pd_service.service_self_update())
    if argv[:1] == ["--apply-update"]:
        INST.apply_update_from_here(VERSION)
        return

    ap = argparse.ArgumentParser(description="PilotDesk – zdalny pulpit")
    ap.add_argument("--host", action="store_true", help="tylko udostępnianie, bez okna")
    ap.add_argument("--minimized", action="store_true")
    ap.add_argument("--set-password", action="store_true")
    ap.add_argument("--relay", help="adres serwera pośredniczącego (pusty = wyłącz)")
    ap.add_argument("--relay-key")
    ap.add_argument("--port", type=int, help="port połączeń bezpośrednich")
    ap.add_argument("--autostart", choices=["on", "off"])
    ap.add_argument("--enable", action="store_true", help="włącz udostępnianie")
    ap.add_argument("--show-id", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args(argv)

    if a.uninstall:
        run_uninstall_gui()
        return
    cfg = load_config()
    if ensure_host_identity(cfg):
        save_config(cfg)
    hpath = host_config_path()
    hcfg = load_config(hpath) if hpath != config_path() else cfg
    changed = False
    for attr, key in (("relay", "relay"), ("relay_key", "relay_key"), ("port", "listen_port")):
        val = getattr(a, attr)
        if val:
            hcfg[key] = val.strip() if isinstance(val, str) else val
            changed = True
    if a.relay == "":
        hcfg["relay"] = ""
        changed = True
    if a.enable:
        hcfg["host_enabled"] = True
        changed = True
    if changed:
        save_config(hcfg, hpath)
    if a.set_password:
        cli_set_password(hcfg, hpath)
    if a.autostart:
        INST.set_autostart(a.autostart == "on")
        print("Autostart:", "włączony" if a.autostart == "on" else "wyłączony")
    if a.show_id:
        print_ids(hcfg)
    if a.host:
        run_headless(hcfg)
        return
    if a.set_password or a.autostart or a.show_id or changed:
        return
    run_gui(cfg, a.minimized)


if __name__ == "__main__":
    main()
