"""PilotDesk – okno sesji z kartami (wiele połączeń), czat, menedżer plików, baner „ktoś jest połączony”."""
import io
import json
import os
import queue
import struct
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

import customtkinter as ctk
from PIL import Image, ImageEnhance, ImageTk

import pd_clipfiles as CF
import pd_media as MEDIA
import pd_theme as T
import pd_ui as U
from pd_common import (
    M_AUDIO, M_FILE, M_FRAME, M_JSON, M_VIDEO, AuthError, FileReceiver, downloads_dir, human_size,
    iter_path_files, list_dir, send_file,
)

IS_MAC = sys.platform == "darwin"

SPECIAL_KEYS = {
    "Return": "enter", "KP_Enter": "enter", "BackSpace": "backspace", "Tab": "tab", "ISO_Left_Tab": "tab",
    "Escape": "esc", "Delete": "delete", "KP_Delete": "delete", "Insert": "insert", "KP_Insert": "insert",
    "Home": "home", "KP_Home": "home", "End": "end", "KP_End": "end", "Prior": "page_up", "KP_Prior": "page_up",
    "Next": "page_down", "KP_Next": "page_down", "Left": "left", "Right": "right", "Up": "up", "Down": "down",
    "KP_Left": "left", "KP_Right": "right", "KP_Up": "up", "KP_Down": "down", "Shift_L": "shift",
    "Shift_R": "shift_r", "Control_L": "ctrl_l", "Control_R": "ctrl_r", "Alt_L": "alt_l", "Alt_R": "alt_r",
    "Option_L": "alt_l", "Option_R": "alt_r", "ISO_Level3_Shift": "alt_gr", "Super_L": "cmd", "Super_R": "cmd_r",
    "Win_L": "cmd", "Win_R": "cmd_r", "Meta_L": "cmd", "Meta_R": "cmd_r", "Caps_Lock": "caps_lock",
    "Num_Lock": "num_lock", "Scroll_Lock": "scroll_lock", "Pause": "pause", "Print": "print_screen",
    "Menu": "menu", "App": "menu", "space": "space",
}
SPECIAL_KEYS.update({f"F{i}": f"f{i}" for i in range(1, 21)})

PUNCT = {
    "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$", "percent": "%", "ampersand": "&",
    "apostrophe": "'", "parenleft": "(", "parenright": ")", "asterisk": "*", "plus": "+", "comma": ",",
    "minus": "-", "period": ".", "slash": "/", "colon": ":", "semicolon": ";", "less": "<", "equal": "=",
    "greater": ">", "question": "?", "at": "@", "bracketleft": "[", "backslash": "\\", "bracketright": "]",
    "asciicircum": "^", "underscore": "_", "grave": "`", "braceleft": "{", "bar": "|", "braceright": "}",
    "asciitilde": "~",
}

QUALITY_PRESETS = [
    ("Najlepsza jakość", {"quality": 85, "scale": 1.0, "fps": 30}),
    ("Zrównoważona", {"quality": 60, "scale": 1.0, "fps": 30}),
    ("Szybkość", {"quality": 45, "scale": 0.75, "fps": 24}),
    ("Słabe łącze", {"quality": 30, "scale": 0.5, "fps": 12}),
]

SHORTCUTS = (("Alt+Tab", "alt_tab"), ("Klawisz Windows", "win"), ("Menedżer zadań", "task_manager"),
             ("Ctrl+Alt+Del (ekran logowania – w trybie usługi)", "ctrl_alt_del"), ("Alt+F4", "alt_f4"),
             ("Pokaż pulpit (Win+D)", "win_d"), ("Eksplorator (Win+E)", "win_e"), ("Zablokuj komputer", "lock"),
             ("Print Screen", "print_screen"))


def key_payload(e):
    ks = e.keysym
    if ks in SPECIAL_KEYS:
        return {"special": SPECIAL_KEYS[ks]}
    ch = e.char
    if ch and len(ch) == 1 and ord(ch) >= 32 and ord(ch) != 127:
        return {"char": ch} if ord(ch) < 128 else {"text": ch}
    if len(ks) == 1:
        return {"char": ks} if ord(ks) < 128 else {"text": ks}
    if ks in PUNCT:
        return {"char": PUNCT[ks]}
    return None


def audio_playback_ok():
    try:
        import soundcard  # noqa
        return MEDIA.opus_ok()
    except Exception:
        return False


def viewer_caps():
    return {"h264": MEDIA.h264_decoder_ok(), "audio": audio_playback_ok(), "clipfiles": CF.available()}


def fmt_speed(bps):
    return f"{bps / 1048576:.1f} MB/s" if bps > 1048576 else f"{bps / 1024:.0f} KB/s"


# =========================================================================== okno z kartami

class SessionsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.views = []
        self.active = None
        self.fullscreen = False
        self.title("PilotDesk – sesje")
        self.geometry("1360x880")
        self.minsize(820, 520)
        self.configure(fg_color=T.BG)
        T.apply_window_icon(self)
        T.apply_dark_title_bar(self, U.dark())

        self.tabbar = ctk.CTkFrame(self, fg_color=T.SIDEBAR, corner_radius=0, height=42)
        self.tabbar.pack(side="top", fill="x")
        self.tabbar.pack_propagate(False)
        ctk.CTkLabel(self.tabbar, text="", image=T.ctk_logo(20)).pack(side="left", padx=(12, 8))
        self.tabs = ctk.CTkFrame(self.tabbar, fg_color="transparent")
        self.tabs.pack(side="left", fill="y", pady=5)
        U.icon_button(self.tabbar, "plus", self.app.show_connect, tip="Nowe połączenie", width=30, height=30).pack(
            side="left", padx=4)
        U.hairline(self, side="top", fill="x")
        self.content = ctk.CTkFrame(self, fg_color=T.BG, corner_radius=0)
        self.content.pack(fill="both", expand=True)
        self.fs_pill = ctk.CTkButton(self, text="  Wyjdź z pełnego ekranu", image=T.icon("exit_fullscreen", 14, "#FFFFFF"),
                                     command=self.toggle_fullscreen, height=28, corner_radius=14, fg_color="#18181B",
                                     hover_color="#27272A", text_color="#FFFFFF", font=T.font(12))
        self.bind("<Control-Alt-Return>", lambda e: (self.toggle_fullscreen(), "break")[1])
        self.bind("<KeyPress>", lambda e: self.active.on_key(e, True) if self.active else None)
        self.bind("<KeyRelease>", lambda e: self.active.on_key(e, False) if self.active else None)
        self.bind("<FocusOut>", lambda e: self.active.on_focus_out() if self.active else None)
        self.protocol("WM_DELETE_WINDOW", self.close_all)

    def add(self, conn, ch, hello, ok):
        v = SessionView(self, conn)
        tab = ctk.CTkFrame(self.tabs, fg_color="transparent", corner_radius=8, height=32)
        tab.pack(side="left", padx=2)
        v.tab_dot = U.dot(tab, T.AMBER, 7)
        v.tab_dot.pack(side="left", padx=(10, 4))
        v.tab_lbl = ctk.CTkLabel(tab, text=conn["name"][:22], font=T.font(12, "medium"), text_color=T.TEXT, height=28)
        v.tab_lbl.pack(side="left")
        U.icon_button(tab, "x", lambda: v.close(), size=12, width=22, height=22, corner_radius=6).pack(side="left", padx=(6, 6))
        for w in (tab, v.tab_lbl, v.tab_dot):
            w.bind("<Button-1>", lambda e: self.activate(v))
        v.tab = tab
        self.views.append(v)
        self.activate(v)
        v.attach(ch, hello, ok)
        self.deiconify()
        self.lift()
        return v

    def activate(self, v):
        if self.active is v:
            return
        if self.active:
            self.active.on_focus_out()
            self.active.pack_forget()
        self.active = v
        v.pack(fill="both", expand=True)
        for x in self.views:
            x.tab.configure(fg_color=T.SURFACE_3 if x is v else "transparent")
            x.tab_lbl.configure(text_color=T.TEXT if x is v else T.TEXT_2)
        self.title(f"{v.conn['name']} – PilotDesk")
        v.dirty = True
        self.after(50, v.canvas.focus_set)

    def remove(self, v):
        if v in self.views:
            self.views.remove(v)
            v.tab.destroy()
            if self.active is v:
                self.active = None
                v.pack_forget()
                if self.views:
                    self.activate(self.views[-1])
        if not self.views:
            self.app.sessions_win = None
            self.destroy()

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.attributes("-fullscreen", self.fullscreen)
        for v in self.views:
            v.set_chrome(not self.fullscreen)
        if self.fullscreen:
            self.tabbar.pack_forget()
            self.fs_pill.place(relx=0.5, y=6, anchor="n")
            self.fs_pill.lift()
        else:
            self.fs_pill.place_forget()
            self.tabbar.pack(side="top", fill="x", before=self.content)
        if self.active:
            self.active.dirty = True
            self.active.canvas.focus_set()

    def close_all(self):
        if len(self.views) > 1 and not U.confirm(self, "Zamknąć wszystkie sesje?", f"Otwartych połączeń: {len(self.views)}.",
                                                 "Zamknij wszystkie", danger=True):
            return
        for v in list(self.views):
            v.close()


# =========================================================================== jedna sesja

class SessionView(ctk.CTkFrame):
    def __init__(self, win, conn):
        super().__init__(win.content, fg_color=T.BG, corner_radius=0)
        self.win = win
        self.app = win.app
        self.conn = conn  # target, name, mode, pw_key, salt
        self.remote_name = conn["name"]
        self.remote_os = ""
        self.hcaps = {}
        self.alive = True
        self.gen = 0
        self.ch = None
        self.uiq = queue.Queue()
        self.sendq = queue.Queue()
        self.fb = None
        self.photo = None
        self.view = None
        self.dirty = False
        self.pressed = {}
        self.last_move = 0.0
        self.pending_move = None
        self.move_scheduled = False
        self.files = FileReceiver()
        self.save_dirs = {}
        self.transfers = {}
        self.fm = None
        self.chat = None
        self.monitors = []
        self.cur_monitor = 1
        self.frames = 0
        self.last_stat = (time.time(), 0, 0)
        self.rtt = None
        self.codec = "—"
        self.req_counter = 0
        self.ls_handlers = {}
        self.op_handlers = {}
        self.fit = True
        self.clip_sync = True
        self.input_enabled = True
        self.audio_on = True
        self.privacy_on = False
        self.preset = QUALITY_PRESETS[1][0]
        self.reboot_pending = False
        self.reconnecting = False
        self.player = None
        self.clip = None
        self.mac = ""
        self._build()
        self.after(10, self._tick)
        self.after(1000, self._stat_tick)

    # ---------------------------------------------------------------- UI
    def _build(self):
        self.bar = ctk.CTkFrame(self, fg_color=T.BG, corner_radius=0, height=50)
        self.bar.pack(side="top", fill="x")
        self.bar.pack_propagate(False)
        left = ctk.CTkFrame(self.bar, fg_color="transparent")
        left.pack(side="left", padx=16)
        self.title_lbl = U.label(left, self.remote_name, 13, "medium")
        self.title_lbl.pack(anchor="w", pady=(7, 0))
        self.stats_lbl = U.label(left, "łączenie…", 11, color=T.TEXT_3, mono=True, height=14)
        self.stats_lbl.pack(anchor="w")

        U.danger_button(self.bar, "Rozłącz", self.close, height=30, width=86).pack(side="right", padx=(8, 14))
        tools = ctk.CTkFrame(self.bar, fg_color="transparent")
        tools.pack(side="right", pady=(6, 0))

        def sep():
            ctk.CTkFrame(tools, fg_color=T.BORDER, width=1, height=20).pack(side="left", padx=6, pady=(0, 8))

        def chip(icon, cmd, tip, toggle=False, on=False):
            c = U.Chip(tools, icon, cmd, tip, toggle, on)
            c.pack(side="left", padx=1)
            return c

        chip("folder", self.open_files, "Pliki")
        chip("upload", self.send_files_dialog, "Wyślij pliki")
        chip("chat", self.open_chat, "Czat i tekst")
        sep()
        self.c_mon = chip("monitor", self._menu_monitors, "Monitor")
        self.c_q = chip("sliders", self._menu_quality, "Jakość obrazu")
        self.c_keys = chip("keyboard", self._menu_keys, "Skróty klawiszowe")
        sep()
        self.c_clip = chip("clipboard", self._toggle_clip, "Wspólny schowek (tekst i pliki)", True, True)
        self.c_audio = chip("speaker", self._toggle_audio, "Dźwięk z komputera zdalnego", True, True)
        self.c_input = chip("mouse", self._toggle_input, "Sterowanie (wyłączone = tylko podgląd)", True, True)
        self.c_priv = chip("privacy", self._toggle_privacy, "Tryb prywatności – czarny ekran na komputerze zdalnym", True, False)
        sep()
        self.c_fit = chip("fit", self._toggle_fit, "Dopasuj obraz do okna / 1:1", True, True)
        chip("fullscreen", self.win.toggle_fullscreen, "Pełny ekran (Ctrl+Alt+Enter)")
        self.c_more = chip("more", self._menu_more, "Więcej")
        self.sep_line = U.hairline(self, side="top", fill="x")

        self.wrap = tk.Frame(self, bg="#09090B")
        self.wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.wrap, bg="#09090B", highlightthickness=0, cursor="arrow", takefocus=True)
        self.hbar = ctk.CTkScrollbar(self.wrap, orientation="horizontal", command=self.canvas.xview)
        self.vbar = ctk.CTkScrollbar(self.wrap, orientation="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.wrap.rowconfigure(0, weight=1)
        self.wrap.columnconfigure(0, weight=1)
        self.img_item = self.canvas.create_image(0, 0, anchor="nw")
        self.ov_title = self.canvas.create_text(0, 0, text="Łączenie z ekranem…", fill="#EDEDF0", font=(T.SANS, 15))
        self.ov_sub = self.canvas.create_text(0, 0, text="", fill="#8A8A93", font=(T.MONO, 10))
        c = self.canvas
        c.bind("<Configure>", lambda e: self._layout_overlay())
        c.bind("<Motion>", self.on_motion)
        c.bind("<ButtonPress>", lambda e: self.on_button(e, True))
        c.bind("<ButtonRelease>", lambda e: self.on_button(e, False))
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Shift-MouseWheel>", lambda e: self.on_wheel(e, horizontal=True))

    def set_chrome(self, show):
        if show:
            self.bar.pack(side="top", fill="x", before=self.wrap)
            self.sep_line.pack(side="top", fill="x", before=self.wrap)
        else:
            self.bar.pack_forget()
            self.sep_line.pack_forget()

    def _overlay(self, title, sub=""):
        self.canvas.itemconfigure(self.ov_title, text=title, state="normal")
        self.canvas.itemconfigure(self.ov_sub, text=sub, state="normal")
        self.canvas.tag_raise(self.ov_title)
        self.canvas.tag_raise(self.ov_sub)
        self._layout_overlay()
        if self.fb is not None and title:
            dim = ImageEnhance.Brightness(self.fb).enhance(0.28)
            self._render(dim)

    def _hide_overlay(self):
        self.canvas.itemconfigure(self.ov_title, state="hidden")
        self.canvas.itemconfigure(self.ov_sub, state="hidden")

    def _layout_overlay(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        x0, y0 = self.canvas.canvasx(0), self.canvas.canvasy(0)
        self.canvas.coords(self.ov_title, x0 + w // 2, y0 + h // 2 - 10)
        self.canvas.coords(self.ov_sub, x0 + w // 2, y0 + h // 2 + 18)
        self.dirty = True

    def toast(self, text, kind="info", ms=3500):
        U.Toast(self.win, text, kind, ms)

    # ---------------------------------------------------------------- połączenie
    def attach(self, ch, hello, ok):
        self.gen += 1
        gen = self.gen
        self.ch = ch
        self.remote_name = self.conn.get("custom") or ok.get("name") or self.remote_name
        self.remote_os = ok.get("os", "")
        self.hcaps = ok.get("caps") or {}
        self.mac = ok.get("mac", "")
        self.title_lbl.configure(text=self.remote_name + (f"   ·   {self.remote_os}" if self.remote_os else ""))
        self.tab_lbl.configure(text=self.remote_name[:22])
        self.tab_dot.configure(image=T.icon("dot", 11, T.GREEN))
        self.reconnecting = False
        self.reboot_pending = False
        self.frames = 0
        self.last_stat = (time.time(), 0, 0)
        self.files = FileReceiver()
        self.sendq = queue.Queue()
        self._overlay("Łączenie z ekranem…", "")
        threading.Thread(target=self._recv_loop, args=(ch, gen), daemon=True).start()
        threading.Thread(target=self._send_loop, args=(ch, gen), daemon=True).start()
        threading.Thread(target=self._pinger, args=(gen,), daemon=True).start()
        for name, s in QUALITY_PRESETS:
            if name == self.preset:
                self.send_json({"t": "settings", **s})
        # dźwięk
        audio_ok = self.hcaps.get("audio") and audio_playback_ok()
        if audio_ok:
            if not self.player:
                try:
                    self.player = MEDIA.AudioPlayer()
                except Exception:
                    audio_ok = False
            if self.player and self.audio_on:
                self.player.start()
                self.send_json({"t": "audio", "on": True})
        self.c_audio.set(bool(audio_ok and self.audio_on))
        self.audio_ok = audio_ok
        self.c_priv.set(False)
        self.privacy_on = False
        # schowek (tekst + pliki)
        if self.clip:
            self.clip.stop()
        try:
            import pyperclip  # noqa
            self.clip = CF.ClipboardSync(
                lambda o: self.send_json(o),
                lambda full, rel, extra, cancel: send_file(ch, full, rel, extra=extra, cancel=cancel,
                                                           progress=self._clip_progress),
                enabled=lambda: self.clip_sync and self.win.active is self,
                notice=lambda t: self.uiq.put(("toast", t)),
                files_enabled=bool(self.hcaps.get("clipfiles")))
            self.clip.start()
        except Exception:
            self.clip = None
        if self.app:
            self.app.on_session_attached(self, ok)

    def _live(self, gen):
        return self.alive and gen == self.gen

    def send_json(self, obj):
        if self.alive:
            self.sendq.put(obj)

    def _send_loop(self, ch, gen):
        q = self.sendq
        while self._live(gen):
            try:
                obj = q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                ch.send_json(obj)
            except Exception as e:
                if self._live(gen):
                    self.uiq.put(("closed", (gen, str(e))))
                return

    def _pinger(self, gen):
        while self._live(gen):
            self.send_json({"t": "ping", "ts": time.time()})
            time.sleep(2)

    def _clip_progress(self, tid, rel, sent, size, status):
        self.uiq.put(("xfer", (tid, "Schowek: " + rel, "up", sent, size, status)))

    def _recv_loop(self, ch, gen):
        dec = None
        try:
            while self._live(gen):
                t, body = ch.recv()
                if t == M_FRAME:
                    self.uiq.put(("frame", self._decode_frame(body)))
                elif t == M_VIDEO:
                    _seq, W, H, _key = struct.unpack_from(">IHHB", body, 0)
                    try:
                        if dec is None:
                            dec = MEDIA.VideoDecoder()
                        img = dec.decode(bytes(body[9:]))
                    except Exception:
                        dec, img = None, None
                        self.send_json({"t": "refresh"})
                    self.uiq.put(("frame", (W, H, [(0, 0, img)] if img else [])))
                elif t == M_AUDIO:
                    if self.player and self.audio_on:
                        self.player.feed(bytes(body))
                elif t == M_FILE:
                    r = self.files.chunk(body)
                    if r:
                        tid, e = r
                        now = time.time()
                        if now - e["last"] > 0.25:
                            e["last"] = now
                            self.uiq.put(("xfer", (tid, e["label"], "down", e["got"], e["size"], "trwa")))
                elif t == M_JSON:
                    m = json.loads(body)
                    mt = m.get("t")
                    if mt == "file_begin":
                        if m.get("clip"):
                            base = CF.ClipboardSync.clip_dir(m["clip"])
                        else:
                            base = self.save_dirs.get(m.get("req")) or downloads_dir()
                        try:
                            e = self.files.begin(m, base)
                            e["label"] = ("Schowek: " if m.get("clip") else "") + e["name"]
                            self.uiq.put(("xfer", (m["id"], e["label"], "down", 0, e["size"], "trwa")))
                        except OSError as ex:
                            self.uiq.put(("toast_err", f"Nie mogę zapisać pliku: {ex}"))
                    elif mt == "file_end":
                        e = self.files.end(m)
                        if e:
                            self.uiq.put(("xfer", (m["id"], e["label"], "down", e["size"], e["size"], "zapisano: " + e["path"])))
                    elif mt == "file_cancel":
                        e = self.files.cancel(m.get("id"))
                        if e:
                            self.uiq.put(("xfer", (m["id"], e.get("label", e["name"]), "down", e["got"], e["size"], "anulowano")))
                    elif mt == "clip_files_end":
                        if self.clip:
                            self.clip.remote_files_end(m)
                    elif mt == "clipboard":
                        if self.clip and self.clip_sync and isinstance(m.get("text"), str):
                            self.clip.remote_text(m["text"])
                    else:
                        self.uiq.put(("json", m))
        except Exception as e:
            if self._live(gen):
                self.uiq.put(("closed", (gen, str(e) or e.__class__.__name__)))
        finally:
            self.files.close_all()

    def _decode_frame(self, body):
        _seq, W, H, n, _flags = struct.unpack_from(">IHHHB", body, 0)
        off = 11
        tiles = []
        for _ in range(n):
            x, y, w, h, ln = struct.unpack_from(">HHHHI", body, off)
            off += 12
            img = Image.open(io.BytesIO(body[off:off + ln]))
            img.load()
            off += ln
            tiles.append((x, y, img))
        return W, H, tiles

    # ---------------------------------------------------------------- ponowne łączenie
    def _connection_lost(self, gen, reason):
        if gen != self.gen or not self.alive or self.reconnecting:
            return
        import pd_log
        pd_log.info("Utracono połączenie z %s: %s", self.remote_name, reason)
        self.reconnecting = True
        self.tab_dot.configure(image=T.icon("dot", 11, T.AMBER))
        if self.player:
            self.player.stop()
        if self.clip:
            self.clip.stop()
        try:
            self.ch.close()
        except Exception:
            pass
        limit = 600 if self.reboot_pending else 90
        title = "Komputer się restartuje…" if self.reboot_pending else "Połączenie przerwane"
        self._overlay(title, "czekam na komputer i łączę ponownie")
        threading.Thread(target=self._reconnect_loop, args=(self.gen, limit, title), daemon=True).start()

    def _reconnect_loop(self, gen, limit, title):
        end = time.time() + limit
        attempt = 0
        time.sleep(5 if self.reboot_pending else 1)
        while self.alive and gen == self.gen and time.time() < end:
            attempt += 1
            self.uiq.put(("overlay", (title, f"próba {attempt} · zostało {int(end - time.time())} s")))
            try:
                res = self.app.open_connection(self.conn["target"], mode=self.conn["mode"],
                                               saved={"salt": self.conn.get("salt"), "key": self.conn.get("pw_key")})
                self.uiq.put(("reattach", (gen, res)))
                return
            except AuthError as e:
                self.uiq.put(("overlay", ("Nie można połączyć ponownie", str(e))))
                return
            except Exception:
                time.sleep(3)
        if self.alive and gen == self.gen:
            self.uiq.put(("overlay", ("Komputer nie odpowiada", "zamknij kartę albo połącz się ponownie z okna głównego")))

    # ---------------------------------------------------------------- pętla UI
    def _tick(self):
        if not self.alive:
            return
        try:
            self._tick_inner()
        except Exception:
            import pd_log
            pd_log.exception("Błąd w oknie sesji")
        if self.alive:
            self.after(10, self._tick)

    def _tick_inner(self):
        try:
            for _ in range(100):
                kind, data = self.uiq.get_nowait()
                if kind == "frame":
                    W, H, tiles = data
                    if tiles:
                        if self.fb is None or self.fb.size != (W, H):
                            self.fb = Image.new("RGB", (W, H))
                        for x, y, img in tiles:
                            self.fb.paste(img, (x, y))
                        if not self.reconnecting:
                            self._hide_overlay()
                        self.dirty = True
                        self.frames += 1
                    self.send_json({"t": "ack"})
                elif kind == "json":
                    self._on_json(data)
                elif kind == "xfer":
                    self._update_transfer(*data)
                elif kind == "toast":
                    self.toast(data, "ok")
                elif kind == "toast_err":
                    self.toast(data, "error", 5000)
                elif kind == "overlay":
                    self._overlay(*data)
                elif kind == "closed":
                    self._connection_lost(*data)
                elif kind == "reattach":
                    gen, (ch, hello, ok, _key) = data
                    if gen == self.gen and self.alive:
                        self.attach(ch, hello, ok)
                        self.toast("Połączono ponownie.", "ok")
                    else:
                        ch.close()
        except queue.Empty:
            pass
        if self.dirty and self.fb is not None and not self.reconnecting and self.win.active is self:
            self.dirty = False
            self._render(self.fb)

    def _render(self, src):
        cw, chh = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        W, H = src.size
        if self.fit:
            s = min(cw / W, chh / H)
            dw, dh = max(1, int(W * s)), max(1, int(H * s))
            ox, oy = (cw - dw) // 2, (chh - dh) // 2
            self.canvas.configure(scrollregion=(0, 0, cw, chh))
            self.hbar.grid_remove()
            self.vbar.grid_remove()
        else:
            dw, dh = W, H
            ox, oy = max(0, (cw - W) // 2), max(0, (chh - H) // 2)
            self.canvas.configure(scrollregion=(0, 0, max(cw, W), max(chh, H)))
            (self.hbar.grid(row=1, column=0, sticky="ew") if W > cw else self.hbar.grid_remove())
            (self.vbar.grid(row=0, column=1, sticky="ns") if H > chh else self.vbar.grid_remove())
        img = src if (dw, dh) == (W, H) else src.resize((dw, dh), Image.BILINEAR)
        if self.photo is None or self.photo.width() != dw or self.photo.height() != dh:
            self.photo = ImageTk.PhotoImage(img)
            self.canvas.itemconfigure(self.img_item, image=self.photo)
        else:
            self.photo.paste(img)
        self.canvas.coords(self.img_item, ox, oy)
        self.view = (ox, oy, dw, dh)

    def _stat_tick(self):
        if not self.alive:
            return
        t0, f0, b0 = self.last_stat
        now = time.time()
        dt = max(0.001, now - t0)
        bin_ = self.ch.bytes_in if self.ch else 0
        fps = (self.frames - f0) / dt
        speed = (bin_ - b0) / dt
        self.last_stat = (now, self.frames, bin_)
        parts = [self.codec.upper() if self.codec != "—" else "—"]
        if self.rtt is not None:
            parts.append(f"{self.rtt:.0f} ms")
        parts += [f"{fps:.0f} kl/s", fmt_speed(speed)]
        if self.fb:
            parts.append(f"{self.fb.size[0]}×{self.fb.size[1]}")
        active = [t for t in self.transfers.values() if t["status"] == "trwa"]
        if active:
            t = active[0]
            pct = 100 * t["done"] / t["size"] if t["size"] else 100
            parts.append(f"{'↑' if t['dir'] == 'up' else '↓'} {os.path.basename(t['name'])[:24]} {pct:.0f}%")
        if not self.input_enabled:
            parts.append("tylko podgląd")
        if self.reconnecting:
            parts = ["ponowne łączenie…"]
        self.stats_lbl.configure(text="  ·  ".join(parts))
        self.after(1000, self._stat_tick)

    def _on_json(self, m):
        t = m.get("t")
        if t == "pong":
            self.rtt = (time.time() - float(m.get("ts", time.time()))) * 1000
        elif t == "codec":
            self.codec = m.get("name", "—")
        elif t == "monitors":
            self.monitors = m.get("list", [])
            self.cur_monitor = m.get("current", 1)
        elif t == "chat":
            self.open_chat()
            self.chat.add(self.remote_name, m.get("text", ""), mine=False)
        elif t == "ls_result":
            h = self.ls_handlers.pop(m.get("req"), None)
            if h:
                h(m)
        elif t == "op_result":
            h = self.op_handlers.pop(m.get("req"), None)
            if h:
                h(m)
        elif t == "file_saved":
            tr = self.transfers.get(m.get("id"))
            if tr:
                self._update_transfer(m["id"], tr["name"], "up", tr["size"], tr["size"], "zapisano: " + m.get("path", ""))
            if self.fm:
                self.fm.remote_refresh_soon()
        elif t == "file_error":
            tr = self.transfers.get(m.get("id"))
            if tr:
                self._update_transfer(m["id"], tr["name"], "up", tr["done"], tr["size"], "błąd: " + m.get("error", ""))
        elif t == "get_error":
            self.toast(f"Błąd pobierania: {m.get('error')}", "error", 5000)
        elif t == "get_done":
            self.save_dirs.pop(m.get("req"), None)
            if self.fm:
                self.fm.local_refresh()
        elif t == "clip_files_begin":
            self.toast(f"Odbieranie plików ze schowka ({human_size(m.get('total', 0))})…")
        elif t == "privacy_state":
            self.privacy_on = bool(m.get("on"))
            self.c_priv.set(self.privacy_on)
            if m.get("error"):
                self.toast(m["error"], "error", 6000)
            elif self.privacy_on:
                self.toast("Tryb prywatności włączony" + ("" if m.get("blocked") else
                                                          " (lokalna mysz i klawiatura nie są zablokowane)"), "ok")
        elif t == "notice":
            self.toast(m.get("text", ""), m.get("kind", "info"), 12000)
        elif t == "rebooting":
            self.reboot_pending = True
            self.toast("Komputer zdalny się restartuje – połączę się ponownie automatycznie.", "info", 6000)
        elif t == "error":
            self.toast(m.get("text", "Błąd"), "error", 6000)

    def next_req(self):
        self.req_counter += 1
        return self.req_counter

    def request_ls(self, path, handler):
        r = self.next_req()
        self.ls_handlers[r] = handler
        self.send_json({"t": "ls", "req": r, "path": path})

    def request_op(self, op, handler, **kw):
        r = self.next_req()
        self.op_handlers[r] = handler
        self.send_json({"t": op, "req": r, **kw})

    # ---------------------------------------------------------------- przełączniki i menu
    def _toggle_clip(self):
        self.clip_sync = not self.clip_sync
        self.c_clip.set(self.clip_sync)
        self.toast("Wspólny schowek " + ("włączony" if self.clip_sync else "wyłączony"))

    def _toggle_audio(self):
        if not getattr(self, "audio_ok", False):
            self.toast("Dźwięk niedostępny na jednym z komputerów.", "warn")
            return
        self.audio_on = not self.audio_on
        self.c_audio.set(self.audio_on)
        self.c_audio.set_icon("speaker" if self.audio_on else "speaker_off")
        self.send_json({"t": "audio", "on": self.audio_on})
        if self.player:
            (self.player.start() if self.audio_on else self.player.stop())

    def _toggle_input(self):
        self.input_enabled = not self.input_enabled
        if not self.input_enabled:
            self.on_focus_out()
        self.c_input.set(self.input_enabled)
        self.toast("Sterowanie włączone" if self.input_enabled else "Tryb tylko podglądu")

    def _toggle_privacy(self):
        if not self.hcaps.get("privacy"):
            self.toast("Tryb prywatności działa tylko na komputerach z Windows 10/11.", "warn")
            return
        self.send_json({"t": "privacy", "on": not self.privacy_on})

    def _toggle_fit(self):
        self.fit = not self.fit
        self.c_fit.set(self.fit)
        self.dirty = True

    def _menu_quality(self):
        def pick(name, s):
            self.preset = name
            self.send_json({"t": "settings", **s})
        items = [(("✓ " if n == self.preset else "    ") + n, lambda n=n, s=s: pick(n, s)) for n, s in QUALITY_PRESETS]
        items += [None, ("    Wymuś JPEG (bez H.264)", lambda: self.send_json({"t": "settings", "codec": "jpeg"})),
                  ("    Automatycznie (H.264, gdy możliwe)", lambda: self.send_json({"t": "settings", "codec": "auto"}))]
        U.popup_menu(self.c_q, items)

    def _menu_monitors(self):
        if not self.monitors:
            return

        def pick(i):
            self.cur_monitor = i
            self.send_json({"t": "monitor", "index": i})
        U.popup_menu(self.c_mon, [(("✓ " if i == self.cur_monitor else "    ") + f"Monitor {i}  ·  {m['w']}×{m['h']}",
                                   lambda i=i: pick(i)) for i, m in enumerate(self.monitors, start=1)])

    def _menu_keys(self):
        U.popup_menu(self.c_keys, [(lbl, lambda n=n: self.send_json({"t": "shortcut", "name": n})) for lbl, n in SHORTCUTS])

    def _menu_more(self):
        U.popup_menu(self.c_more, [
            ("Uruchom ponownie komputer zdalny…", self._ask_reboot),
            ("Odśwież obraz", lambda: self.send_json({"t": "refresh"})),
            None,
            ("Kopiuj adres MAC (Wake-on-LAN)", self._copy_mac),
        ])

    def _ask_reboot(self):
        if U.confirm(self.win, "Zrestartować komputer zdalny?",
                     f"{self.remote_name} uruchomi się ponownie za 3 s. Niezapisana praca może zostać utracona. "
                     "PilotDesk połączy się ponownie, gdy komputer wróci (z usługą – już na ekranie logowania).",
                     "Restartuj", danger=True, icon="restart"):
            self.send_json({"t": "reboot"})

    def _copy_mac(self):
        if self.mac:
            self.clipboard_clear()
            self.clipboard_append(self.mac)
            self.toast(f"Skopiowano {self.mac}", "ok")
        else:
            self.toast("Adres MAC nieznany.", "warn")

    # ---------------------------------------------------------------- transfery
    def _update_transfer(self, tid, name, direction, done, size, status):
        prev = self.transfers.get(tid)
        self.transfers[tid] = {"name": name, "dir": direction, "done": done, "size": size, "status": status}
        if (status.startswith("zapisano") and (not prev or not prev["status"].startswith("zapisano"))
                and direction == "down" and not name.startswith("Schowek") and not (self.fm and self.fm.winfo_exists())):
            self.toast(f"Pobrano: {os.path.basename(name)}", "ok")
        if self.fm and self.fm.winfo_exists():
            self.fm.show_transfer(tid, self.transfers[tid])

    def upload(self, paths, dest=None):
        def progress(tid, rel, sent, size, status):
            self.uiq.put(("xfer", (tid, rel, "up", sent, size, status)))
        ch = self.ch

        def worker():
            for p in paths:
                try:
                    for full, rel in iter_path_files(p):
                        if not self.alive:
                            return
                        send_file(ch, full, rel, extra={"dest": dest} if dest else None, progress=progress)
                except Exception as e:
                    if self.alive:
                        self.uiq.put(("toast_err", f"Błąd wysyłania {os.path.basename(p)}: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def download(self, remote_path, local_dir):
        r = self.next_req()
        self.save_dirs[r] = local_dir
        self.send_json({"t": "get", "req": r, "path": remote_path})

    def send_files_dialog(self):
        paths = filedialog.askopenfilenames(parent=self.win, title="Wybierz pliki do wysłania")
        if paths:
            self.upload(list(paths))
            self.toast(f"Wysyłanie {len(paths)} plik(ów) do Pobrane/PilotDesk na komputerze zdalnym.")
        self.canvas.focus_set()

    def open_files(self):
        if self.fm and self.fm.winfo_exists():
            self.fm.deiconify()
            self.fm.lift()
        else:
            self.fm = FileManager(self)

    def open_chat(self):
        if self.chat and self.chat.winfo_exists():
            self.chat.deiconify()
            self.chat.lift()
        else:
            self.chat = ChatWindow(self.win, self.remote_name, on_send=lambda t: self.send_json({"t": "chat", "text": t}),
                                   on_clip=self._remote_clip, on_type=lambda t: self.send_json({"t": "type_text", "text": t}))

    def _remote_clip(self, t):
        if self.clip:
            self.clip.text_last = t
        self.send_json({"t": "clipboard", "text": t})

    # ---------------------------------------------------------------- mysz i klawiatura
    def _norm(self, e):
        if not self.view:
            return None
        ox, oy, dw, dh = self.view
        x = self.canvas.canvasx(e.x) - ox
        y = self.canvas.canvasy(e.y) - oy
        return (min(max(x / dw, 0.0), 1.0), min(max(y / dh, 0.0), 1.0))

    def _input_ok(self):
        return self.input_enabled and not self.reconnecting

    def on_motion(self, e):
        if not self._input_ok():
            return
        p = self._norm(e)
        if p is None:
            return
        self.pending_move = p
        if time.time() - self.last_move >= 0.016:
            self._flush_move()
        elif not self.move_scheduled:
            self.move_scheduled = True
            self.after(16, self._flush_move)

    def _flush_move(self):
        self.move_scheduled = False
        if self.pending_move:
            x, y = self.pending_move
            self.pending_move = None
            self.last_move = time.time()
            self.send_json({"t": "mouse_move", "x": x, "y": y})

    def on_button(self, e, down):
        self.canvas.focus_set()
        if not self._input_ok():
            return
        if e.num in (4, 5):
            if down:
                self.send_json({"t": "wheel", "dx": 0, "dy": 1 if e.num == 4 else -1})
            return
        if e.num in (6, 7):
            if down:
                self.send_json({"t": "wheel", "dx": -1 if e.num == 6 else 1, "dy": 0})
            return
        names = {1: "left", 2: "right", 3: "middle"} if IS_MAC else {1: "left", 2: "middle", 3: "right"}
        b = names.get(e.num)
        p = self._norm(e)
        if down and getattr(self, "_clicks_logged", 0) < 3:  # diagnostyka: czy kliknięcia w ogóle wychodzą
            self._clicks_logged = getattr(self, "_clicks_logged", 0) + 1
            import pd_log
            pd_log.info("Okno sesji %s: klik num=%s → %s, pozycja %s, obraz %s", self.remote_name, e.num, b, p,
                        self.view)
        if b and p:
            self.pending_move = None
            self.send_json({"t": "mouse_btn", "b": b, "down": down, "x": p[0], "y": p[1]})

    def on_wheel(self, e, horizontal=False):
        if not self._input_ok():
            return
        d = e.delta if IS_MAC else e.delta / 120
        steps = int(d) if abs(d) >= 1 else (1 if d > 0 else -1)
        self.send_json({"t": "wheel", "dx": -steps, "dy": 0} if horizontal else {"t": "wheel", "dx": 0, "dy": steps})

    def on_key(self, e, down):
        if e.widget is not self.win and e.widget is not self.canvas:
            return None
        if not self._input_ok():
            return "break"
        if down:
            p = key_payload(e)
            if not p:
                return "break"
            self.pressed[e.keycode] = p
        else:
            p = self.pressed.pop(e.keycode, None) or key_payload(e)
            if not p or "text" in p:
                return "break"
        self.send_json({"t": "key", "down": down, "k": p})
        return "break"

    def on_focus_out(self, _e=None):
        for p in self.pressed.values():
            if "text" not in p:
                self.send_json({"t": "key", "down": False, "k": p})
        self.pressed.clear()

    # ---------------------------------------------------------------- zamykanie
    def close(self):
        """Rozłącz – natychmiast. Pożegnalne komunikaty (puszczenie klawiszy, wyłączenie prywatności) wysyłamy
        w tle z krótkim limitem czasu, żeby zablokowane połączenie nie zawieszało okna."""
        ch = self.ch
        bye = []
        if self.alive and ch:
            bye = [{"t": "key", "down": False, "k": p} for p in self.pressed.values() if "text" not in p]
            if self.privacy_on:
                bye.append({"t": "privacy", "on": False})
        self.pressed.clear()
        self.alive = False
        self.gen += 1
        try:
            import pd_log
            pd_log.info("Rozłączono sesję z %s", self.remote_name)
        except Exception:
            pass
        for x in (self.player, self.clip):
            if x:
                x.stop()

        def goodbye():
            try:
                if bye:
                    ch.sock.settimeout(2)
                    for m in bye:
                        ch.send_json(m)
            except Exception:
                pass
            finally:
                try:
                    ch.close()
                except Exception:
                    pass
        if ch:
            threading.Thread(target=goodbye, name="disconnect", daemon=True).start()
        for w in (self.fm, self.chat):
            try:
                if w:
                    w.destroy()
            except Exception:
                pass
        self.win.remove(self)
        try:
            self.destroy()
        except Exception:
            pass


# =========================================================================== czat

class ChatWindow(ctk.CTkToplevel):
    def __init__(self, master, name, on_send, on_clip=None, on_type=None):
        super().__init__(master)
        self.on_send, self.on_clip, self.on_type = on_send, on_clip, on_type
        self.title(f"Czat – {name}")
        self.geometry("440x580")
        self.minsize(360, 420)
        self.configure(fg_color=T.BG)
        T.apply_window_icon(self)
        T.apply_dark_title_bar(self, U.dark())
        head = ctk.CTkFrame(self, fg_color="transparent", height=54)
        head.pack(fill="x", padx=18)
        head.pack_propagate(False)
        U.dot(head, T.GREEN, 7).pack(side="left")
        U.label(head, name, 14, "medium").pack(side="left", padx=8)
        U.hairline(self, fill="x")
        self.log = ctk.CTkTextbox(self, fg_color=T.BG, font=T.font(13), wrap="word", text_color=T.TEXT, border_width=0)
        self.log.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        self.log.tag_config("me_name", justify="right", foreground="#8A8A93", spacing1=10)
        self.log.tag_config("me", justify="right", lmargin1=70, lmargin2=70, spacing3=2)
        self.log.tag_config("them_name", justify="left", foreground="#8A8A93", spacing1=10)
        self.log.tag_config("them", justify="left", rmargin=70, spacing3=2)
        self.log.tag_config("sys", justify="center", foreground="#6B6B75", spacing1=8, spacing3=8)
        self.log.configure(state="disabled")
        box = U.card(self)
        box.pack(fill="x", padx=12, pady=(4, 12))
        self.inp = ctk.CTkTextbox(box, height=80, fg_color=T.SURFACE, font=T.font(13), wrap="word", text_color=T.TEXT,
                                  border_width=0)
        self.inp.pack(fill="x", padx=6, pady=(6, 2))
        self.inp.bind("<Return>", self._enter)
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(0, 8))
        U.primary_button(row, "Wyślij", self.send_msg, height=30, width=76).pack(side="right")
        if on_clip:
            b = U.secondary_button(row, "Do schowka", self.to_clipboard, icon="clipboard", height=30, width=110)
            b.pack(side="left")
            U.Tooltip(b, "Tekst trafi do schowka komputera zdalnego (wklej Ctrl+V)")
        if on_type:
            b = U.secondary_button(row, "Wpisz", self.type_remote, icon="keyboard", height=30, width=84)
            b.pack(side="left", padx=6)
            U.Tooltip(b, "Wpisze tekst na komputerze zdalnym jak z klawiatury")
        self.after(250, self.inp.focus_set)

    def _enter(self, e):
        if e.state & 0x0001:
            return None
        self.send_msg()
        return "break"

    def _text(self):
        return self.inp.get("1.0", "end-1c")

    def add(self, who, text, mine=False, system=False):
        self.log.configure(state="normal")
        if system:
            self.log.insert("end", text + "\n", "sys")
        else:
            tag = "me" if mine else "them"
            self.log.insert("end", f"{who} · {time.strftime('%H:%M')}\n", tag + "_name")
            self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def send_msg(self):
        t = self._text().strip()
        if t:
            self.on_send(t)
            self.add("Ty", t, mine=True)
            self.inp.delete("1.0", "end")

    def to_clipboard(self):
        t = self._text()
        if t:
            self.on_clip(t)
            self.add("", f"wysłano do schowka zdalnego · {len(t)} znaków", system=True)

    def type_remote(self):
        t = self._text()
        if t:
            self.on_type(t)
            self.add("", f"wpisano na komputerze zdalnym · {len(t)} znaków", system=True)


# =========================================================================== baner na komputerze sterowanym

class ConnectedBanner(ctk.CTkToplevel):
    """Okienko „Sesja zdalna aktywna” na sterowanym komputerze. Można je zminimalizować do małej karteczki
    „● Zdalnie” – coś zawsze zostaje widoczne, żeby było wiadomo, że ktoś jest połączony."""

    W = 300

    def __init__(self, master, on_disconnect, on_chat, minimized=False, on_toggle=None):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=T.BORDER_STRONG)
        self.on_toggle = on_toggle
        self.minimized = False
        self._moved = False
        self._dx = self._dy = 0

        # --- pełny widok
        self.full = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=0)
        top = ctk.CTkFrame(self.full, fg_color="transparent")
        top.pack(fill="x", padx=(14, 6), pady=(8, 0))
        U.dot(top, T.RED, 7).pack(side="left")
        title = U.label(top, "Sesja zdalna aktywna", 13, "medium")
        title.pack(side="left", padx=6)
        U.icon_button(top, "minus", lambda: self.set_minimized(True), tip="Zminimalizuj", size=14, width=28,
                      height=28).pack(side="right")
        self.who = U.label(self.full, "", 12, color=T.TEXT_2, mono=True)
        self.who.pack(anchor="w", padx=14)
        row = ctk.CTkFrame(self.full, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(8, 12))
        U.secondary_button(row, "Czat", on_chat, height=28, width=70).pack(side="left")
        U.danger_button(row, "Rozłącz", on_disconnect, height=28, width=90).pack(side="right")
        for w in (self.full, top, title, self.who):
            w.bind("<ButtonPress-1>", self._start)
            w.bind("<B1-Motion>", self._drag)

        # --- karteczka po zminimalizowaniu (klik = rozwiń, przeciągnięcie = przesuń)
        self.mini = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=0)
        mrow = ctk.CTkFrame(self.mini, fg_color="transparent")
        mrow.pack(padx=10, pady=5)
        mdot = U.dot(mrow, T.RED, 7)
        mdot.pack(side="left")
        mlbl = U.label(mrow, "Zdalnie", 12, "medium", cursor="hand2")
        mlbl.pack(side="left", padx=(6, 0))
        for w in (self.mini, mrow, mdot, mlbl):
            w.bind("<ButtonPress-1>", self._start)
            w.bind("<B1-Motion>", self._drag)
            w.bind("<ButtonRelease-1>", self._mini_release)
        U.Tooltip(mlbl, "Ktoś steruje tym komputerem – kliknij, aby pokazać szczegóły")

        self.full.pack(fill="both", expand=True, padx=1, pady=1)
        self.update_idletasks()
        h = self.winfo_reqheight()
        self.geometry(f"{self.W}x{h}+{self.winfo_screenwidth() - self.W - 20}+{self.winfo_screenheight() - h - 64}")
        if minimized:
            self.set_minimized(True, notify=False)

    def set_sessions(self, names):
        self.who.configure(text=", ".join(names)[:40])

    def set_minimized(self, on, notify=True):
        if on == self.minimized:
            return
        self.update_idletasks()
        x, y = self.winfo_x(), self.winfo_y()
        w, h = self.winfo_width(), self.winfo_height()
        self.minimized = on
        (self.full if on else self.mini).pack_forget()
        (self.mini if on else self.full).pack(fill="both", expand=True, padx=1, pady=1)
        self.update_idletasks()
        nw, nh = (self.mini.winfo_reqwidth() + 2, self.mini.winfo_reqheight() + 2) if on else \
            (self.W, self.full.winfo_reqheight() + 2)
        # zostaje przyklejone do tego samego prawego dolnego rogu
        nx = min(max(0, x + w - nw), self.winfo_screenwidth() - nw)
        ny = min(max(0, y + h - nh), self.winfo_screenheight() - nh)
        self.geometry(f"{nw}x{nh}+{nx}+{ny}")
        if notify and self.on_toggle:
            self.on_toggle(on)

    def _start(self, e):
        self._moved = False
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()
        self._sx, self._sy = e.x_root, e.y_root

    def _drag(self, e):
        if abs(e.x_root - self._sx) + abs(e.y_root - self._sy) > 4:
            self._moved = True
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _mini_release(self, _e):
        if not self._moved:
            self.set_minimized(False)


# =========================================================================== menedżer plików

def _tree_style(widget):
    st = ttk.Style(widget)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    d = U.dark()
    bg = "#111114" if d else "#FFFFFF"
    fg = "#EDEDF0" if d else "#09090B"
    head = "#111114" if d else "#FFFFFF"
    muted = "#6B6B75" if d else "#8A8A93"
    sel = "#232328" if d else "#EBEBEE"
    st.configure("PD.Treeview", background=bg, fieldbackground=bg, foreground=fg, rowheight=28, borderwidth=0,
                 font=(T.SANS, 10))
    st.configure("PD.Treeview.Heading", background=head, foreground=muted, relief="flat", borderwidth=0,
                 font=(T.MONO, 9), padding=(8, 6))
    st.map("PD.Treeview", background=[("selected", sel)], foreground=[("selected", fg)])
    st.map("PD.Treeview.Heading", background=[("active", head)])
    st.layout("PD.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])


class FilePane(ctk.CTkFrame):
    def __init__(self, master, title, on_open):
        super().__init__(master, fg_color=T.SURFACE, corner_radius=12, border_width=1, border_color=T.BORDER)
        self.on_open = on_open
        self.path = ""
        self.parent_path = ""
        self.entries = {}
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 6))
        U.label(head, title.upper(), 11, color=T.TEXT_3, mono=True).pack(side="left")
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=10, pady=(0, 8))
        U.icon_button(nav, "arrow_up", self.go_up, tip="Folder wyżej", width=30, height=30).pack(side="left")
        U.icon_button(nav, "home", lambda: self.on_open(""), tip="Dyski i foldery", width=30, height=30).pack(side="left")
        self.path_e = U.entry(nav, "", height=30, size=12, mono=True)
        self.path_e.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.path_e.bind("<Return>", lambda e: self.on_open(self.path_e.get()))
        U.hairline(self, fill="x", padx=1)
        holder = tk.Frame(self, bg=self._apply_appearance_mode(T.SURFACE))
        holder.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.tree = ttk.Treeview(holder, columns=("size", "mtime"), selectmode="extended", style="PD.Treeview")
        self.tree.heading("#0", text="NAZWA", anchor="w")
        self.tree.heading("size", text="ROZMIAR", anchor="e")
        self.tree.heading("mtime", text="ZMIENIONO", anchor="w")
        self.tree.column("#0", width=250)
        self.tree.column("size", width=80, anchor="e")
        self.tree.column("mtime", width=125)
        sb = ctk.CTkScrollbar(holder, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._dbl)
        self.tree.bind("<Return>", self._dbl)
        self.tree.bind("<BackSpace>", lambda e: self.go_up())
        c = "#A1A1AA" if U.dark() else "#52525B"
        self.ic_dir = ImageTk.PhotoImage(T.icon_pil("folder", c, 16))
        self.ic_file = ImageTk.PhotoImage(T.icon_pil("file", "#6B6B75", 16))

    def show(self, result):
        self.path = result.get("path", "")
        self.parent_path = result.get("parent", "")
        self.path_e.delete(0, "end")
        self.path_e.insert(0, self.path or "dyski i foldery")
        self.tree.delete(*self.tree.get_children())
        self.entries = {}
        if result.get("error"):
            self.tree.insert("", "end", text="  " + result["error"])
        for e in result.get("entries", []):
            mt = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["mtime"])) if e.get("mtime") else ""
            iid = self.tree.insert("", "end", text="  " + e["name"], image=self.ic_dir if e["dir"] else self.ic_file,
                                   values=("" if e["dir"] else human_size(e["size"]), mt))
            self.entries[iid] = e

    def _dbl(self, _e=None):
        sel = self.tree.selection()
        if sel and sel[0] in self.entries and self.entries[sel[0]]["dir"]:
            self.on_open(self.entries[sel[0]]["path"])

    def go_up(self):
        self.on_open(self.parent_path if self.path else "")

    def selected(self):
        return [self.entries[i] for i in self.tree.selection() if i in self.entries]


class FileManager(ctk.CTkToplevel):
    def __init__(self, sess):
        super().__init__(sess.win)
        self.sess = sess
        self.title(f"Pliki – {sess.remote_name}")
        self.geometry("1200x760")
        self.minsize(900, 560)
        self.configure(fg_color=T.BG)
        T.apply_window_icon(self)
        T.apply_dark_title_bar(self, U.dark())
        _tree_style(self)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(16, 8))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(2, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.local = FilePane(body, "ten komputer", self.local_open)
        self.local.grid(row=0, column=0, sticky="nsew")
        mid = ctk.CTkFrame(body, fg_color="transparent", width=130)
        mid.grid(row=0, column=1, sticky="ns", padx=12)
        b = U.primary_button(mid, "Wyślij", self.do_upload, icon="arrow_right", width=132)
        b.configure(compound="right")
        b.pack(pady=(90, 8))
        U.primary_button(mid, "Pobierz", self.do_download, icon="arrow_left", width=132).pack(pady=0)
        U.hairline(mid, fill="x", pady=18)
        for text, cmd, ic in (("Nowy folder", self.do_mkdir, "plus"), ("Zmień nazwę", self.do_rename, "edit"),
                              ("Odśwież", self.refresh_both, "refresh")):
            U.secondary_button(mid, text, cmd, icon=ic, width=132).pack(pady=3)
        U.danger_button(mid, "Usuń", self.do_delete, icon="trash", width=132).pack(pady=3)
        self.remote = FilePane(body, sess.remote_name, self.remote_open)
        self.remote.grid(row=0, column=2, sticky="nsew")
        U.section(self, "transfery", padx=16, pady=(6, 4))
        self.xlist = ctk.CTkScrollableFrame(self, fg_color="transparent", height=84)
        self.xlist.pack(fill="x", padx=12, pady=(0, 12))
        self.xempty = U.label(self.xlist, "Brak transferów. Zaznacz pliki i kliknij „Wyślij” lub „Pobierz”.", 12, color=T.TEXT_3)
        self.xempty.pack(anchor="w", padx=6, pady=4)
        self.xrows = {}
        for tid, t in sess.transfers.items():
            self.show_transfer(tid, t)
        self._refresh_pending = False
        self.local_open(os.path.expanduser("~"))
        self.remote_open("")

    def show_transfer(self, tid, t):
        if not self.winfo_exists():
            return
        if self.xempty:
            self.xempty.destroy()
            self.xempty = None
        row = self.xrows.get(tid)
        if not row:
            first = next((w for w in self.xlist.winfo_children() if w.winfo_manager()), None)
            row = ctk.CTkFrame(self.xlist, fg_color="transparent")
            row.pack(fill="x", pady=1, **({"before": first} if first is not None else {}))
            U.label(row, "↑" if t["dir"] == "up" else "↓", 12, color=T.TEXT_3, mono=True, width=16).pack(side="left", padx=(6, 6))
            row.name = U.label(row, os.path.basename(t["name"])[:44], 12, width=300, anchor="w")
            row.name.pack(side="left")
            row.bar = ctk.CTkProgressBar(row, width=180, height=4, progress_color=T.TEXT_2, fg_color=T.SURFACE_3)
            row.bar.pack(side="left", padx=10)
            row.info = U.label(row, "", 11, color=T.TEXT_3, anchor="w", mono=True)
            row.info.pack(side="left", fill="x", expand=True)
            self.xrows[tid] = row
        pct = t["done"] / t["size"] if t["size"] else 1.0
        row.bar.set(pct)
        st = t["status"]
        done = st.startswith("zapisano") or st == "wysłano"
        row.bar.configure(progress_color=T.GREEN if done else (T.RED if st.startswith("błąd") else T.TEXT_2))
        text = f"{pct * 100:.0f}%  {human_size(t['done'])} / {human_size(t['size'])}" if st == "trwa" else st
        row.info.configure(text=text[:90], text_color=T.RED if st.startswith("błąd") else T.TEXT_3)

    def local_open(self, path):
        try:
            r = list_dir(path)
        except Exception as e:
            r = {"path": path, "parent": os.path.dirname(path), "entries": [], "error": str(e)}
        self.local.show(r)

    def local_refresh(self):
        if self.winfo_exists():
            self.local_open(self.local.path)

    def remote_open(self, path):
        self.sess.request_ls(path, lambda r: self.winfo_exists() and self.remote.show(r))

    def remote_refresh_soon(self):
        if not self._refresh_pending:
            self._refresh_pending = True

            def go():
                self._refresh_pending = False
                if self.winfo_exists():
                    self.remote_open(self.remote.path)
            self.after(700, go)

    def refresh_both(self):
        self.local_refresh()
        self.remote_open(self.remote.path)

    def _toast(self, t, kind="warn"):
        U.Toast(self, t, kind)

    def do_upload(self):
        sel = self.local.selected()
        if not sel:
            self._toast("Zaznacz pliki lub foldery po lewej stronie.")
        elif not self.remote.path:
            self._toast("Po prawej wejdź najpierw do folderu docelowego.")
        else:
            self.sess.upload([e["path"] for e in sel], dest=self.remote.path)

    def do_download(self):
        sel = self.remote.selected()
        if not sel:
            self._toast("Zaznacz pliki lub foldery po prawej stronie.")
        elif not self.local.path:
            self._toast("Po lewej wejdź najpierw do folderu docelowego.")
        else:
            for e in sel:
                self.sess.download(e["path"], self.local.path)

    def _op_done(self, r):
        if not r.get("ok"):
            self._toast(r.get("error", "Błąd"), "error")
        self.remote_open(self.remote.path)

    def _join_remote(self, name):
        base = self.remote.path
        sep = "\\" if ("\\" in base or (len(base) >= 2 and base[1] == ":")) else "/"
        return base.rstrip("\\/") + sep + name

    def do_mkdir(self):
        if not self.remote.path:
            return
        name = U.ask_string(self, "Nowy folder", "Nazwa folderu na komputerze zdalnym:", icon="folder")
        if name:
            self.sess.request_op("mkdir", self._op_done, path=self._join_remote(name))

    def do_rename(self):
        sel = self.remote.selected()
        if len(sel) != 1:
            self._toast("Zaznacz jeden element po prawej stronie.")
            return
        name = U.ask_string(self, "Zmień nazwę", "Nowa nazwa:", sel[0]["name"])
        if name and name != sel[0]["name"]:
            self.sess.request_op("rename", self._op_done, path=sel[0]["path"], new=self._join_remote(name))

    def do_delete(self):
        sel = self.remote.selected()
        if not sel:
            return
        names = ", ".join(e["name"] for e in sel[:5]) + (" …" if len(sel) > 5 else "")
        if U.confirm(self, "Usunąć na komputerze zdalnym?", f"{names}\nPliki zostaną usunięte trwale (bez kosza).",
                     "Usuń", danger=True, icon="trash"):
            for e in sel:
                self.sess.request_op("delete", self._op_done, path=e["path"])
