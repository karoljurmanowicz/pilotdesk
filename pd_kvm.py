"""PilotDesk – wspólna mysz i klawiatura („przejście kursora na komputer obok”).

Jak to działa:
  * KvmLink – połączenie z drugim komputerem BEZ obrazu (tylko mysz, klawiatura, schowek i pliki),
  * EdgeSwitch – pilnuje kursora; gdy dotknie ustawionej krawędzi ekranu, mysz i klawiatura tego
    komputera są przechwytywane i trafiają do komputera obok. Powrót: przesunięcie kursora z powrotem
    przez tę samą krawędź albo Ctrl+Alt+Esc (awaryjnie zawsze działa też Ctrl+Alt+Del),
  * ArrangementCanvas – wizualizacja ekranów; ekran komputera obok przeciąga się myszą na właściwą stronę.
"""
import json
import queue
import threading
import time

from pd_common import M_FILE, M_JSON, FileReceiver, send_file

SIDES = ("right", "left", "top", "bottom")
SIDE_NAMES = {"right": "po prawej", "left": "po lewej", "top": "nad", "bottom": "pod"}


def local_desktop():
    """(lewo, góra, szerokość, wysokość) całego pulpitu oraz lista monitorów."""
    import mss
    with (getattr(mss, "MSS", None) or mss.mss)() as s:
        mons = s.monitors
        allm = mons[0]
        return (allm["left"], allm["top"], allm["width"], allm["height"]), [
            (m["left"], m["top"], m["width"], m["height"]) for m in mons[1:]]


def key_to_payload(key):
    """pynput Key/KeyCode -> format protokołu PilotDesk."""
    from pynput.keyboard import Key, KeyCode
    if isinstance(key, Key):
        return {"special": key.name}
    if isinstance(key, KeyCode):
        c = key.char
        vk = getattr(key, "vk", None)
        if c and len(c) == 1 and ord(c) >= 32 and ord(c) != 127:
            return {"char": c} if ord(c) < 128 else {"text": c}
        if vk and (0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39):  # Ctrl+litera daje znak sterujący – bierzemy klawisz
            return {"char": chr(vk).lower()}
        if c and len(c) == 1 and 1 <= ord(c) <= 26:
            return {"char": chr(ord(c) + 96)}
    return None


# =========================================================================== połączenie bez obrazu

class KvmLink:
    def __init__(self, app, entry, on_state, clip_enabled=lambda: True):
        self.app = app
        self.entry = entry
        self.on_state = on_state  # (stan, opis)
        self.clip_enabled = clip_enabled
        self.running = False
        self.ch = None
        self.gen = 0
        self.monitors = []
        self.rtt = None
        self.clip = None
        self.files = FileReceiver()
        self.name = entry.get("name") or entry["addr"]
        self.monitor = 1

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._connect_loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.gen += 1
        if self.clip:
            self.clip.stop()
        if self.ch:
            try:
                self.ch.close()
            except Exception:
                pass
        self.ch = None

    @property
    def connected(self):
        return self.ch is not None

    def send_json(self, obj):
        ch = self.ch
        if ch:
            try:
                ch.send_json(obj)
            except Exception:
                pass

    def remote_size(self):
        if self.monitors and 1 <= self.monitor <= len(self.monitors):
            m = self.monitors[self.monitor - 1]
            return m["w"], m["h"]
        return self.entry.get("kvm_w", 1920), self.entry.get("kvm_h", 1080)

    def set_monitor(self, idx):
        self.monitor = idx
        self.send_json({"t": "monitor", "index": idx})

    def _connect_loop(self):
        from pd_common import AuthError
        first = True
        while self.running:
            self.on_state("connecting", f"Łączenie z {self.name}…" if first else f"Ponowne łączenie z {self.name}…")
            try:
                ch, hello, ok, _k = self.app.open_connection(
                    self.entry["addr"], saved={"salt": self.entry.get("salt"), "key": self.entry.get("key")},
                    on_code=lambda c: self.on_state("waiting", f"Zaakceptuj połączenie na {self.name} (kod {c[:3]} {c[3:]})"),
                    extra={"video": False})
            except AuthError as e:
                self.on_state("error", str(e))
                self.running = False
                return
            except Exception as e:
                self.on_state("connecting", f"{self.name} nie odpowiada – ponawiam… ({str(e)[:60]})")
                for _ in range(10):
                    if not self.running:
                        return
                    time.sleep(0.5)
                first = False
                continue
            if not self.running:
                ch.close()
                return
            self.gen += 1
            gen = self.gen
            self.ch = ch
            self.name = ok.get("name") or self.name
            ch.send_json({"t": "video", "on": False})
            ch.send_json({"t": "monitor", "index": self.monitor})
            try:
                import pd_clipfiles as CF
                import pyperclip  # noqa
                if self.clip:
                    self.clip.stop()
                self.clip = CF.ClipboardSync(self.send_json,
                                             lambda full, rel, extra, cancel: send_file(ch, full, rel, extra=extra, cancel=cancel),
                                             enabled=self.clip_enabled,
                                             notice=lambda t: self.on_state("notice", t),
                                             files_enabled=bool((ok.get("caps") or {}).get("clipfiles")))
                self.clip.start()
            except Exception:
                self.clip = None
            self.on_state("connected", f"Połączono z {self.name}")
            threading.Thread(target=self._pinger, args=(gen,), daemon=True).start()
            self._recv(ch, gen)
            if self.clip:
                self.clip.stop()
            self.ch = None
            if self.running:
                self.on_state("connecting", f"Utracono połączenie z {self.name} – ponawiam…")
                time.sleep(2)
                first = False

    def _pinger(self, gen):
        while self.running and gen == self.gen:
            self.send_json({"t": "ping", "ts": time.time()})
            time.sleep(2)

    def _recv(self, ch, gen):
        import pd_clipfiles as CF
        try:
            while self.running and gen == self.gen:
                t, body = ch.recv()
                if t == M_FILE:
                    self.files.chunk(body)
                elif t == M_JSON:
                    m = json.loads(body)
                    mt = m.get("t")
                    if mt == "monitors":
                        self.monitors = m.get("list", [])
                        w, h = self.remote_size()
                        self.entry["kvm_w"], self.entry["kvm_h"] = w, h
                        self.on_state("monitors", "")
                    elif mt == "pong":
                        self.rtt = (time.time() - float(m.get("ts", time.time()))) * 1000
                    elif mt == "clipboard":
                        if self.clip and self.clip_enabled() and isinstance(m.get("text"), str):
                            self.clip.remote_text(m["text"])
                    elif mt == "file_begin" and m.get("clip"):
                        try:
                            self.files.begin(m, CF.ClipboardSync.clip_dir(m["clip"]))
                        except OSError:
                            pass
                    elif mt == "file_end":
                        self.files.end(m)
                    elif mt == "file_cancel":
                        self.files.cancel(m.get("id"))
                    elif mt == "clip_files_end":
                        if self.clip:
                            self.clip.remote_files_end(m)
                    elif mt == "notice":
                        self.on_state("notice", m.get("text", ""))
                    elif mt == "chat":
                        self.on_state("notice", f"Wiadomość od {self.name}: {m.get('text', '')}")
        except Exception:
            pass
        finally:
            self.files.close_all()


# =========================================================================== przełączanie na krawędzi

class EdgeSwitch:
    """Wykrywa dotknięcie krawędzi i przełącza mysz/klawiaturę na drugi komputer."""

    def __init__(self, link, layout, on_state):
        self.link = link
        self.layout = layout  # dict: side, offset, delay
        self.on_state = on_state  # ("local"|"remote")
        self.lock = threading.RLock()
        self.remote = False
        self.running = False
        self.watch = None
        self.ml = self.kl = None
        self.edge_since = None
        self.pressed = {}
        self.mods = set()
        self.buttons = set()
        self.q = queue.Queue()

    # ---------------------------------------------------------------- start / stop
    def start(self):
        from pynput import mouse
        self.desk, self.mons = local_desktop()
        self.mouse = mouse.Controller()
        self.running = True
        self.watch = mouse.Listener(on_move=self._watch_move)
        self.watch.start()
        threading.Thread(target=self._sender, daemon=True).start()

    def stop(self):
        self.running = False
        self.leave(reason="stop")
        if self.watch:
            self.watch.stop()
            self.watch = None
        self.q.put(None)

    def _sender(self):
        """Wysyłanie poza wątkiem haków (haki muszą wracać natychmiast)."""
        while self.running:
            obj = self.q.get()
            if obj is None:
                return
            self.link.send_json(obj)

    def send(self, obj):
        self.q.put(obj)

    # ---------------------------------------------------------------- geometria
    def _remote_span(self):
        rw, rh = self.link.remote_size()
        side = self.layout.get("side", "right")
        return (rh if side in ("left", "right") else rw), rw, rh

    def _at_edge(self, x, y):
        """Zwraca pozycję wejścia na zdalnym ekranie albo None."""
        dx, dy, dw, dh = self.desk
        side = self.layout.get("side", "right")
        span, rw, rh = self._remote_span()
        off = int(self.layout.get("offset", 0))
        if side == "right" and x >= dx + dw - 1:
            a = y - dy - off
            return (0, a) if 0 <= a < span else None
        if side == "left" and x <= dx:
            a = y - dy - off
            return (rw - 1, a) if 0 <= a < span else None
        if side == "bottom" and y >= dy + dh - 1:
            a = x - dx - off
            return (a, 0) if 0 <= a < span else None
        if side == "top" and y <= dy:
            a = x - dx - off
            return (a, rh - 1) if 0 <= a < span else None
        return None

    def _watch_move(self, x, y):
        if not self.running or self.remote or not self.link.connected:
            self.edge_since = None
            return
        entry = self._at_edge(x, y)
        if entry is None:
            self.edge_since = None
            return
        delay = float(self.layout.get("delay", 0))
        now = time.time()
        if delay <= 0:
            self.enter(*entry)
        elif self.edge_since is None:
            self.edge_since = now
            threading.Timer(delay, self._delayed_check).start()
        elif now - self.edge_since >= delay:
            self.enter(*entry)

    def _delayed_check(self):
        if self.edge_since is None or self.remote or not self.running:
            return
        entry = self._at_edge(*self.mouse.position)
        if entry is not None:
            self.enter(*entry)

    # ---------------------------------------------------------------- tryb zdalny
    def enter(self, rx, ry):
        from pynput import keyboard, mouse
        with self.lock:
            if self.remote or not self.running:
                return
            self.remote = True
            self.edge_since = None
            self.rx, self.ry = rx, ry
            mx, my, mw, mh = self._monitor_at(*self.mouse.position)
            self.center = (mx + mw // 2, my + mh // 2)
            self.mouse.position = self.center
            self.pressed.clear()
            self.mods.clear()
            self.buttons.clear()
            self._send_pos()
            self.ml = mouse.Listener(on_move=self._r_move, on_click=self._r_click, on_scroll=self._r_scroll, suppress=True)
            self.kl = keyboard.Listener(on_press=self._r_press, on_release=self._r_release, suppress=True)
            self.ml.start()
            self.kl.start()
        self.on_state("remote")

    def leave(self, reason="edge", local_pos=None):
        with self.lock:
            if not self.remote:
                return
            self.remote = False
            for p in list(self.pressed.values()):  # puść wszystko po drugiej stronie
                self.send({"t": "key", "down": False, "k": p})
            for b in list(self.buttons):
                self.send({"t": "mouse_btn", "b": b, "down": False, "x": self._nx(), "y": self._ny()})
            self.pressed.clear()
            self.buttons.clear()
            for lst in (self.ml, self.kl):
                if lst:
                    try:
                        lst.stop()
                    except Exception:
                        pass
            self.ml = self.kl = None
            try:
                self.mouse.position = local_pos or self.center
            except Exception:
                pass
        self.on_state("local")

    def _monitor_at(self, x, y):
        for m in self.mons:
            if m[0] <= x < m[0] + m[2] and m[1] <= y < m[1] + m[3]:
                return m
        return self.mons[0] if self.mons else self.desk

    def _nx(self):
        rw, _ = self.link.remote_size()
        return min(max(self.rx / max(1, rw - 1), 0.0), 1.0)

    def _ny(self):
        _, rh = self.link.remote_size()
        return min(max(self.ry / max(1, rh - 1), 0.0), 1.0)

    def _send_pos(self):
        self.send({"t": "mouse_move", "x": self._nx(), "y": self._ny()})

    def _r_move(self, x, y):
        if not self.remote:
            return
        cx, cy = self.center
        ddx, ddy = x - cx, y - cy
        if ddx == 0 and ddy == 0:
            return
        rw, rh = self.link.remote_size()
        self.rx += ddx
        self.ry += ddy
        side = self.layout.get("side", "right")
        dx, dy, dw, dh = self.desk
        off = int(self.layout.get("offset", 0))
        back = None
        if side == "right" and self.rx < 0:
            back = (dx + dw - 3, dy + off + int(self.ry))
        elif side == "left" and self.rx > rw - 1:
            back = (dx + 2, dy + off + int(self.ry))
        elif side == "bottom" and self.ry < 0:
            back = (dx + off + int(self.rx), dy + dh - 3)
        elif side == "top" and self.ry > rh - 1:
            back = (dx + off + int(self.rx), dy + 2)
        if back and not self.buttons:  # z wciśniętym przyciskiem nie wracamy (np. przeciąganie okna)
            bx = min(max(back[0], dx), dx + dw - 1)
            by = min(max(back[1], dy), dy + dh - 1)
            threading.Thread(target=self.leave, kwargs={"local_pos": (bx, by)}, daemon=True).start()
            return
        self.rx = min(max(self.rx, 0), rw - 1)
        self.ry = min(max(self.ry, 0), rh - 1)
        self._send_pos()
        try:
            self.mouse.position = self.center  # kursor tego komputera stoi w miejscu
        except Exception:
            pass

    def _r_click(self, x, y, button, pressed):
        if not self.remote:
            return
        name = getattr(button, "name", "left")
        if name not in ("left", "right", "middle"):
            return
        (self.buttons.add if pressed else self.buttons.discard)(name)
        self.send({"t": "mouse_btn", "b": name, "down": pressed, "x": self._nx(), "y": self._ny()})

    def _r_scroll(self, x, y, dx, dy):
        if self.remote:
            self.send({"t": "wheel", "dx": int(dx), "dy": int(dy)})

    def _r_press(self, key):
        if not self.remote:
            return
        from pynput.keyboard import Key
        if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
            self.mods.add("ctrl")
        if key in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr):
            self.mods.add("alt")
        if key == Key.esc and {"ctrl", "alt"} <= self.mods:  # Ctrl+Alt+Esc – powrót
            threading.Thread(target=self.leave, kwargs={"reason": "hotkey"}, daemon=True).start()
            return
        p = key_to_payload(key)
        if not p:
            return
        if "text" not in p:
            self.pressed[str(key)] = p
        self.send({"t": "key", "down": True, "k": p})

    def _r_release(self, key):
        from pynput.keyboard import Key
        if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
            self.mods.discard("ctrl")
        if key in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr):
            self.mods.discard("alt")
        if not self.remote:
            return
        p = self.pressed.pop(str(key), None) or key_to_payload(key)
        if p and "text" not in p:
            self.send({"t": "key", "down": False, "k": p})


# =========================================================================== wizualizacja ekranów

class ArrangementCanvas:
    """Ekrany tego komputera + przeciągany ekran komputera obok. Po puszczeniu przykleja się do najbliższej
    krawędzi; zielona linia pokazuje, przez którą część krawędzi przechodzi kursor."""

    def __init__(self, master, height, get_remote, on_change, dark=True):
        import tkinter as tk
        self.tk = tk
        self.c = tk.Canvas(master, height=height, highlightthickness=0, bd=0)
        self.get_remote = get_remote  # -> (nazwa, w, h, połączony)
        self.on_change = on_change
        self.layout = {"side": "right", "offset": 0}
        self.dark = dark
        self.drag = None
        self.c.bind("<Configure>", lambda e: self.draw())
        self.c.tag_bind("remote", "<ButtonPress-1>", self._press)
        self.c.tag_bind("remote", "<B1-Motion>", self._motion)
        self.c.tag_bind("remote", "<ButtonRelease-1>", self._release)
        self.c.tag_bind("remote", "<Enter>", lambda e: self.c.configure(cursor="fleur"))
        self.c.tag_bind("remote", "<Leave>", lambda e: self.c.configure(cursor=""))
        try:
            self.desk, self.mons = local_desktop()
        except Exception:
            self.desk, self.mons = (0, 0, 1920, 1080), [(0, 0, 1920, 1080)]

    def pack(self, **kw):
        self.c.pack(**kw)

    def set_layout(self, layout):
        self.layout = dict(layout)
        self.draw()

    def colors(self):
        if self.dark:
            return dict(bg="#111114", mon="#1F1F24", mon_line="#3A3A42", text="#EDEDF0", muted="#8A8A93",
                        rem="#16231C", rem_off="#1A1A1E", green="#3DD68C", line_off="#55555F")
        return dict(bg="#FFFFFF", mon="#F1F1F3", mon_line="#C9C9CF", text="#09090B", muted="#6B6B75",
                    rem="#E8F8EF", rem_off="#F4F4F5", green="#22A866", line_off="#A1A1AA")

    def _remote_rect(self):
        """Prostokąt zdalnego ekranu w układzie pikseli (lokalny pulpit zaczyna się w 0,0)."""
        _n, rw, rh, _c = self.get_remote()
        dx, dy, dw, dh = self.desk
        side, off = self.layout.get("side", "right"), int(self.layout.get("offset", 0))
        if side == "right":
            return (dw, off, rw, rh)
        if side == "left":
            return (-rw, off, rw, rh)
        if side == "bottom":
            return (off, dh, rw, rh)
        return (off, -rh, rw, rh)

    def _transform(self):
        cw, ch = max(50, self.c.winfo_width()), max(50, self.c.winfo_height())
        dx, dy, dw, dh = self.desk
        rx, ry, rw, rh = self._remote_rect()
        x0, y0 = min(0, rx), min(0, ry)
        x1, y1 = max(dw, rx + rw), max(dh, ry + rh)
        s = min((cw - 60) / (x1 - x0), (ch - 56) / (y1 - y0))
        ox = (cw - (x1 - x0) * s) / 2 - x0 * s
        oy = (ch - (y1 - y0) * s) / 2 - y0 * s
        return s, ox, oy

    def draw(self):
        c, col = self.c, self.colors()
        c.delete("all")
        c.configure(bg=col["bg"])
        self.s, self.ox, self.oy = self._transform()
        s, ox, oy = self.s, self.ox, self.oy
        dx, dy, dw, dh = self.desk
        for i, (mx, my, mw, mh) in enumerate(self.mons, start=1):
            x, y = ox + (mx - dx) * s, oy + (my - dy) * s
            c.create_rectangle(x + 2, y + 2, x + mw * s - 2, y + mh * s - 2, fill=col["mon"], outline=col["mon_line"])
            c.create_text(x + mw * s / 2, y + mh * s / 2 - 8, text=str(i), fill=col["text"], font=("PD Geist Medium", 14))
            c.create_text(x + mw * s / 2, y + mh * s / 2 + 12, text=f"{mw}×{mh}", fill=col["muted"], font=("PD Geist Mono", 8))
        c.create_text(ox + dw * s / 2, oy + dh * s + 14, text="TEN KOMPUTER", fill=col["muted"], font=("PD Geist Mono", 8))
        name, rw, rh, connected = self.get_remote()
        rx, ry, _, _ = self._remote_rect()
        x, y = ox + rx * s, oy + ry * s
        c.create_rectangle(x + 2, y + 2, x + rw * s - 2, y + rh * s - 2, fill=col["rem"] if connected else col["rem_off"],
                           outline=col["green"] if connected else col["line_off"], width=2, dash=() if connected else (4, 3),
                           tags=("remote",))
        c.create_text(x + rw * s / 2, y + rh * s / 2 - 8, text=name[:22], fill=col["text"], font=("PD Geist Medium", 11),
                      tags=("remote",))
        c.create_text(x + rw * s / 2, y + rh * s / 2 + 11, text=f"{rw}×{rh}" + ("" if connected else " · niepołączony"),
                      fill=col["muted"], font=("PD Geist Mono", 8), tags=("remote",))
        # wspólna krawędź – tędy przechodzi kursor
        side = self.layout.get("side", "right")
        if side in ("left", "right"):
            ex = ox + (dw if side == "right" else 0) * s
            a0, a1 = max(0, ry), min(dh, ry + rh)
            if a1 > a0:
                c.create_line(ex, oy + a0 * s, ex, oy + a1 * s, fill=col["green"], width=4)
        else:
            ey = oy + (dh if side == "bottom" else 0) * s
            a0, a1 = max(0, rx), min(dw, rx + rw)
            if a1 > a0:
                c.create_line(ox + a0 * s, ey, ox + a1 * s, ey, fill=col["green"], width=4)

    def _press(self, e):
        self.drag = (e.x, e.y)

    def _motion(self, e):
        if not self.drag:
            return
        ddx, ddy = e.x - self.drag[0], e.y - self.drag[1]
        self.drag = (e.x, e.y)
        self.c.move("remote", ddx, ddy)

    def _release(self, e):
        if not self.drag:
            return
        self.drag = None
        box = self.c.bbox("remote")
        if not box:
            return
        s, ox, oy = self.s, self.ox, self.oy
        dx, dy, dw, dh = self.desk
        _n, rw, rh, _c = self.get_remote()
        cx = ((box[0] + box[2]) / 2 - ox) / s  # środek zdalnego ekranu w pikselach układu
        cy = ((box[1] + box[3]) / 2 - oy) / s
        # najbliższa strona: porównujemy, jak daleko środek wychodzi poza lokalny pulpit
        dists = {"right": cx - dw, "left": -cx, "bottom": cy - dh, "top": -cy}
        nx = (cx - dw / 2) / (dw / 2 + rw / 2)
        ny = (cy - dh / 2) / (dh / 2 + rh / 2)
        side = (("right" if nx > 0 else "left") if abs(nx) >= abs(ny) else ("bottom" if ny > 0 else "top"))
        del dists
        if side in ("left", "right"):
            off = int(cy - rh / 2)
            off = max(-rh + rh // 4, min(off, dh - rh // 4))
        else:
            off = int(cx - rw / 2)
            off = max(-rw + rw // 4, min(off, dw - rw // 4))
        # przyciąganie do wyrównania (górą / środkiem / dołem)
        span_l = dh if side in ("left", "right") else dw
        span_r = rh if side in ("left", "right") else rw
        for snap in (0, (span_l - span_r) // 2, span_l - span_r):
            if abs(off - snap) < span_l * 0.06:
                off = snap
                break
        self.layout["side"], self.layout["offset"] = side, off
        self.draw()
        self.on_change(dict(self.layout))
