"""PilotDesk – strona udostępniająca (komputer, którym się steruje)."""
import io
import json
import queue
import os
import platform
import shutil
import socket
import struct
import sys
import threading
import time

import pd_clipfiles as CF
import pd_media as MEDIA
import pd_winutil as W
from pd_common import (
    DEFAULT_PORT, DEFAULT_RELAY_PORT, M_AUDIO, M_FILE, M_FRAME, M_JSON, M_VIDEO, AuthError, FileReceiver,
    downloads_dir, get_mac, has_password, note_remote_input, host_handshake, hostname, iter_path_files, list_dir, open_tcp,
    parse_hostport, recv_line, send_file, send_line, send_wol, tune_socket,
)

if sys.platform == "win32":  # współrzędne w pikselach fizycznych (skalowanie 125%/150%)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

TILE = 64


def _log(msg):
    try:
        import pd_log
        pd_log.info("%s", msg)
    except Exception:
        pass

MOD_NAMES = ("ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr", "shift", "shift_l",
             "shift_r", "cmd", "cmd_l", "cmd_r")
BITRATES = {85: 8_000_000, 60: 4_000_000, 45: 2_000_000, 30: 800_000}


def host_caps():
    return {"h264": MEDIA.h264_encoder_name() is not None, "audio": MEDIA.audio_capture_ok(),
            "privacy": sys.platform == "win32", "clipfiles": CF.available(), "reboot": True}


class Lockout:
    """Ochrona przed zgadywaniem hasła: 10 błędów w 5 min => blokada 60 s."""

    def __init__(self):
        self.fails = []
        self.until = 0.0
        self.lock = threading.Lock()

    def allowed(self):
        return time.time() >= self.until

    def fail(self):
        with self.lock:
            now = time.time()
            self.fails = [t for t in self.fails if now - t < 300] + [now]
            if len(self.fails) >= 10:
                self.until = now + 60
                self.fails = []

    def success(self):
        with self.lock:
            self.fails = []


class HostService:
    """Przyjmuje połączenia (bezpośrednio i przez serwer pośredniczący).

    ask(klient, adres, kod) -> bool  – pytanie „Akceptuj/Odrzuć” (None = tryb bez hasła wyłączony)
    agent_mode – proces agenta usługi Windows (przełączanie na ekran logowania / UAC)."""

    def __init__(self, cfg, log=None, on_chat=None, on_sessions=None, on_status=None, ask=None, agent_mode=False,
                 save_cfg=None):
        self.cfg = cfg
        self.save_cfg = save_cfg
        self.log = log or (lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
        self.on_chat = on_chat
        self.on_sessions = on_sessions
        self.on_status = on_status
        self.ask = ask
        self.agent_mode = agent_mode
        self.sessions = set()
        self.lock = threading.Lock()
        self.running = False
        self.gen = 0
        self.lockout = Lockout()
        self.relay_status = "nie skonfigurowano"
        self.direct_status = "wyłączone"
        self._listen_sock = None
        self._relay_sock = None
        self.caps = host_caps()
        self.discovery = None
        self.listen_port_actual = 0
        self._callbacks = []

    # ---------------------------------------------------------------- start / stop
    def start(self):
        if not has_password(self.cfg) and not (self.ask and self.cfg.get("ask_enabled", True)):
            raise ValueError("Najpierw ustaw hasło dostępu")
        self.running = True
        self.gen += 1
        gen = self.gen
        if self.cfg.get("direct_enabled", True):
            threading.Thread(target=self._listen_loop, args=(gen,), daemon=True).start()
        else:
            self._set_status(direct="wyłączone")
        if self.cfg.get("relay"):
            threading.Thread(target=self._relay_loop, args=(gen,), daemon=True).start()
        else:
            self._set_status(relay="nie skonfigurowano")
        if self.cfg.get("direct_enabled", True) and not self.discovery:
            import pd_discovery
            self.discovery = pd_discovery.Responder(self._discovery_info, on_callback=self._callback)
            if not self.discovery.start():
                self.discovery = None

    def _discovery_info(self):
        if not self.running or not self.cfg.get("direct_enabled", True):
            return None
        return {"id": self.cfg.get("host_id"), "name": hostname(), "os": f"{platform.system()} {platform.release()}",
                "port": int(self.listen_port_actual or 0), "callback": True}

    def _callback(self, ip, port):
        """Połączenie zwrotne: klient nie może się do nas dodzwonić (zapora), więc to my łączymy się z nim.
        Łączymy się tylko z adresem, z którego przyszła prośba, i najwyżej 6 razy na minutę."""
        now = time.time()
        self._callbacks = [t for t in self._callbacks if now - t < 60]
        if not self.running or len(self._callbacks) >= 6 or not (1 <= int(port) <= 65535):
            return
        self._callbacks.append(now)
        try:
            sock = open_tcp(ip, int(port), timeout=6)
        except OSError as e:
            self.log(f"Połączenie zwrotne do {ip} nieudane: {e}")
            return
        self.handle_conn(sock, f"{ip} (połączenie zwrotne)")

    def stop(self, kick=True):
        self.running = False
        self.gen += 1
        for s in (self._listen_sock, self._relay_sock):
            if s:
                try:
                    s.close()
                except OSError:
                    pass
        self._listen_sock = self._relay_sock = None
        self.listen_port_actual = 0
        if self.discovery:
            self.discovery.stop()
            self.discovery = None
        if kick:
            self.disconnect_all()
        self._set_status(direct="wyłączone", relay="wyłączony")

    def disconnect_all(self):
        with self.lock:
            sess = list(self.sessions)
        for s in sess:
            s.stop()

    def _alive(self, gen):
        return self.running and gen == self.gen

    def _set_status(self, direct=None, relay=None):
        if direct is not None:
            self.direct_status = direct
        if relay is not None:
            self.relay_status = relay
        if self.on_status:
            self.on_status()

    # ---------------------------------------------------------------- połączenia bezpośrednie
    def _listen_loop(self, gen):
        """Nasłuch TCP. Gdy port jest zajęty albo zarezerwowany przez Windows (Hyper-V/WSL/Docker),
        używamy zapasowego – wyszukiwanie po ID i tak poda klientom właściwy port."""
        want = int(self.cfg.get("listen_port", DEFAULT_PORT))
        candidates = [want, want] + [p for p in (47810, 47820, 47830, 47850, 47890, 48800, 58800) if p != want] + [0]
        s = None
        last_err = None
        for port in candidates:
            if not self._alive(gen):
                return
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if sys.platform != "win32":
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
                s.listen(16)
                break
            except OSError as e:
                last_err = e
                s.close()
                s = None
                if port == want and getattr(e, "errno", None) in (98, 48, 10048):  # zajęty – może zaraz się zwolni
                    time.sleep(0.7)
        if s is None:
            self.log(f"Nie mogę otworzyć żadnego portu TCP: {last_err}")
            self._set_status(direct="błąd portu")
            return
        port = s.getsockname()[1]
        self.listen_port_actual = port
        if port != want:
            self.log(f"Port {want} jest zajęty lub zablokowany przez system ({last_err}) – używam portu {port}")
        self._listen_sock = s
        self._set_status(direct=f"port {port}")
        self.log(f"Czekam na połączenia bezpośrednie na porcie {port}")
        while self._alive(gen):
            try:
                conn, addr = s.accept()
            except OSError:
                break
            tune_socket(conn)
            threading.Thread(target=self.handle_conn, args=(conn, addr[0]), daemon=True).start()

    # ---------------------------------------------------------------- serwer pośredniczący
    def _relay_loop(self, gen):
        backoff = 3
        while self._alive(gen):
            relay = self.cfg.get("relay", "")
            sock = None
            try:
                h, p = parse_hostport(relay, DEFAULT_RELAY_PORT)
                sock = open_tcp(h, p, timeout=15)
                send_line(sock, {"op": "register", "id": self.cfg["host_id"], "secret": self.cfg["id_secret"],
                                 "key": self.cfg.get("relay_key", "")})
                r = recv_line(sock)
                if not r.get("ok"):
                    err = r.get("error", "odmowa")
                    self.log(f"Serwer pośredniczący odrzucił rejestrację: {err}")
                    self._set_status(relay=f"błąd: {err}")
                    self._sleep(gen, 30)
                    continue
                self._relay_sock = sock
                self._set_status(relay=f"połączony ({relay})")
                self.log(f"Zarejestrowano na serwerze {relay} jako ID {self.cfg['host_id']}")
                backoff = 3
                sock.settimeout(90)
                threading.Thread(target=self._relay_pinger, args=(sock, gen), daemon=True).start()
                while self._alive(gen):
                    m = recv_line(sock)
                    if m.get("op") == "incoming":
                        threading.Thread(target=self._relay_accept, args=(m.get("session", ""),), daemon=True).start()
            except Exception as e:
                if not self._alive(gen):
                    break
                self._set_status(relay=f"rozłączony – ponawiam ({e.__class__.__name__})")
            finally:
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
            self._sleep(gen, backoff)
            backoff = min(backoff * 2, 60)

    def _sleep(self, gen, secs):
        end = time.time() + secs
        while self._alive(gen) and time.time() < end:
            time.sleep(0.5)

    def _relay_pinger(self, sock, gen):
        while self._alive(gen):
            time.sleep(25)
            try:
                send_line(sock, {"op": "ping"})
            except OSError:
                return

    def _relay_accept(self, session_id):
        try:
            h, p = parse_hostport(self.cfg.get("relay", ""), DEFAULT_RELAY_PORT)
            sock = open_tcp(h, p, timeout=15)
            send_line(sock, {"op": "accept", "id": self.cfg["host_id"], "secret": self.cfg["id_secret"],
                             "session": session_id, "key": self.cfg.get("relay_key", "")})
            r = recv_line(sock)
            if not r.get("ok"):
                sock.close()
                return
        except Exception as e:
            self.log(f"Nie udało się przyjąć połączenia przez serwer: {e}")
            return
        self.handle_conn(sock, "przez serwer")

    # ---------------------------------------------------------------- obsługa sesji
    def handle_conn(self, sock, peer):
        sess = None
        hello_sent = [False]
        try:
            _log(f"Połączenie przychodzące od {peer}")
            if not self.lockout.allowed():
                left = max(1, int(self.lockout.until - time.time()))
                self.log(f"Odrzucono połączenie ({peer}) – blokada po zbyt wielu błędnych hasłach")
                _refuse(sock, f"Zbyt wiele nieudanych prób logowania – komputer zdalny przyjmie połączenie za "
                                   f"{left} s.")
                return
            sock.settimeout(20)
            info = {"name": hostname(), "os": f"{platform.system()} {platform.release()}", "mac": get_mac(),
                    "caps": self.caps, "service": self.agent_mode}
            ask_cb = None
            if self.ask:
                def ask_cb(client, code, dev):
                    trusted = {t.get("pub") for t in self.cfg.get("trusted", [])}
                    if dev and dev in trusted:
                        self.log(f"Zapamiętany komputer łączy się bez pytania: {client} ({peer})")
                        return True
                    sock.settimeout(90)
                    self.log(f"Prośba o połączenie: {client} ({peer}), kod {code}")
                    r = self.ask(client, peer, code, dev)
                    ok, remember = (r if isinstance(r, tuple) else (r, False))
                    if ok and remember and dev:
                        self.cfg.setdefault("trusted", []).append({"pub": dev, "name": client, "added": int(time.time())})
                        if self.save_cfg:
                            self.save_cfg()
                        self.log(f"Zapamiętano komputer {client} – następnym razem połączy się bez pytania")
                    return bool(ok)
            hello_sent[0] = True
            try:
                ch, auth, mode = host_handshake(sock, self.cfg, info, ask_cb=ask_cb)
            except AuthError:
                self.lockout.fail()
                self.log(f"Nieudana próba logowania – błędne hasło ({peer})")
                time.sleep(1)
                return
            except PermissionError as e:
                self.log(f"Odrzucono połączenie ({peer}): {e}")
                time.sleep(0.5)
                return
            sock.settimeout(60)
            self.lockout.success()
            sess = HostSession(self, ch, peer, auth, mode)
            with self.lock:
                self.sessions.add(sess)
            self.log(f"Połączono zdalnie: {sess.client} ({peer}){' – po akceptacji' if mode == 'ask' else ''}")
            if self.on_sessions:
                self.on_sessions()
            sess.run()
        except Exception as e:
            if sess is None and isinstance(e, ConnectionError):
                # druga strona rozłączyła się przed zalogowaniem – zwykle „Sprawdź połączenie” albo wyszukiwanie
                _log(f"Połączenie od {peer} zakończone przed zalogowaniem ({e})")
            else:
                self.log(f"Błąd połączenia ({peer}): {e}")
                _log(f"Błąd połączenia ({peer}): {e!r}")
            if not hello_sent[0]:
                _refuse(sock, f"Błąd na komputerze zdalnym: {e}")
        finally:
            try:
                sock.close()
            except OSError:
                pass
            if sess:
                with self.lock:
                    self.sessions.discard(sess)
                self.log(f"Rozłączono: {sess.client}")
                if self.on_sessions:
                    self.on_sessions()


def _refuse(sock, reason):
    """Odmowa przed uzgadnianiem: jawna wiadomość zamiast cichego zamknięcia (klient pokaże powód)."""
    try:
        from pd_common import APP_NAME, PROTO, send_plain
        sock.settimeout(3)
        send_plain(sock, {"app": APP_NAME, "proto": PROTO, "error": reason})
    except Exception:
        pass



class HostSession:
    def __init__(self, svc, ch, peer, auth, mode="password"):
        self.svc = svc
        self.ch = ch
        self.peer = peer
        self.mode = mode
        self.client = str(auth.get("client", "?"))[:80]
        self.vcaps = auth.get("caps") or {}
        self.id = os.urandom(6).hex()
        self.started = time.time()
        self.running = True
        self.fps = 20
        self.quality = 60
        self.scale = 1.0
        self.codec_pref = "auto"
        self.monitor = 1
        self.inflight = 0
        self.cond = threading.Condition()
        self.force_full = True
        self.cur_mon = None
        self.files = FileReceiver()
        self.pressed_keys = {}
        self.pressed_buttons = set()
        self.input_ok = False
        self.cancels = {}
        self.audio = None
        self.privacy = None
        self.blocked = False
        self.clip = None
        self.video_on = auth.get("video", True) is not False
        self.outq = queue.Queue(maxsize=2000)
        self._uipi_check = 0.0
        self._uipi_told = 0.0
        self.win_mouse = sys.platform == "win32"  # mysz przez własne SendInput (pd_winutil), nie pynput
        self._clicks_logged = 0
        self._click_fail_told = 0.0

    # ---------------------------------------------------------------- pętla główna
    def stop(self):
        self.running = False
        with self.cond:
            self.cond.notify_all()
        self.ch.close()

    def send_json(self, obj):
        """Nie blokuje: wiadomości idą przez osobny wątek, więc obsługa myszy/klawiatury nigdy nie czeka na sieć."""
        try:
            self.outq.put_nowait(obj)
        except queue.Full:
            pass

    def _sender(self):
        while self.running:
            try:
                obj = self.outq.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.ch.send_json(obj)
            except Exception:
                self.stop()
                return

    def send_chat(self, text):
        self.send_json({"t": "chat", "text": text})

    def run(self):
        try:
            from pynput import keyboard, mouse
            self.mouse = mouse.Controller()
            self.kb = keyboard.Controller()
            self.Key, self.KeyCode, self.Button = keyboard.Key, keyboard.KeyCode, mouse.Button
            self.mods = {getattr(self.Key, n) for n in MOD_NAMES if hasattr(self.Key, n)}
            self.input_ok = True
        except Exception as e:
            self.svc.log(f"Sterowanie myszą/klawiaturą niedostępne: {e}")
        if self.win_mouse:
            try:
                _log(f"Sesja {self.client}: {W.dpi_info()}, monitory przechwytywania: {self.monitors_info()}")
            except Exception as e:
                _log(f"Diagnostyka DPI nieudana: {e}")
        try:
            import pyperclip  # noqa
            self.clip = CF.ClipboardSync(
                self.send_json, lambda full, rel, extra, cancel: send_file(self.ch, full, rel, extra=extra, cancel=cancel),
                files_enabled=bool(self.vcaps.get("clipfiles")))
            self.clip.start()
        except Exception as e:
            self.svc.log(f"Schowek niedostępny: {e}")
        for target in (self._screen_loop, self._pinger, self._sender):
            threading.Thread(target=target, daemon=True).start()
        try:
            while self.running:
                t, body = self.ch.recv()
                if t == M_JSON:
                    self._handle(json.loads(body))
                elif t == M_FILE:
                    self.files.chunk(body)
        except Exception as e:
            if self.running and not isinstance(e, (ConnectionError, OSError)):
                self.svc.log(f"Błąd sesji: {e}")
        finally:
            self.stop()
            self._release_all()
            self.files.close_all()
            for ev in self.cancels.values():
                ev.set()
            if self.audio:
                self.audio.stop()
            if self.clip:
                self.clip.stop()
            self._set_privacy(False, notify=False)

    def _pinger(self):
        while self.running:
            time.sleep(15)
            if self.running:
                self.send_json({"t": "ping"})

    # ---------------------------------------------------------------- ekran
    def _use_h264(self):
        return (self.codec_pref != "jpeg" and self.vcaps.get("h264") and self.svc.caps.get("h264"))

    def _screen_loop(self):
        try:
            import mss
            import numpy as np
            from PIL import Image
        except Exception as e:
            self.send_json({"t": "error", "text": f"Brak bibliotek do przechwytywania ekranu: {e}"})
            return
        new_mss = getattr(mss, "MSS", None) or mss.mss
        sct = None
        prev = prev_key = None
        enc = None
        enc_key = None
        seq = 0
        last_change = time.time()
        refined = True
        settle = 0
        sent_mons = None
        sent_codec = None
        while self.running:
            t0 = time.time()
            with self.cond:
                while self.running and self.inflight >= 2:
                    self.cond.wait(0.5)
                    if time.time() - t0 > 5:  # zgubione potwierdzenie nie może zamrozić obrazu na zawsze
                        self.inflight = 0
                        self.force_full = True
                        break
            if not self.running:
                break
            try:
                if self.svc.agent_mode and W.sync_input_desktop():
                    if sct:
                        sct.close()
                    sct = None
                    self.force_full = True
                if sct is None:
                    sct = new_mss()
                mons = sct.monitors
                desc = [{"w": m["width"], "h": m["height"], "left": m["left"], "top": m["top"]} for m in mons[1:]]
                idx = self.monitor if 1 <= self.monitor < len(mons) else 1
                if desc != sent_mons:
                    sent_mons = desc
                    self.send_json({"t": "monitors", "list": desc, "current": idx})
                mon = mons[idx]
                self.cur_mon = mon
                if not self.video_on:  # tryb wspólnej myszy – bez obrazu, tylko pozycje monitorów
                    prev = None
                    time.sleep(0.5)
                    continue
                shot = sct.grab(mon)
            except Exception:
                try:
                    if sct:
                        sct.close()
                except Exception:
                    pass
                sct = None
                time.sleep(0.3)
                continue
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            if self.scale < 0.999:
                img = img.resize((max(2, int(img.width * self.scale)), max(2, int(img.height * self.scale))),
                                 Image.BILINEAR)
            arr = np.asarray(img)
            Wd, Hd = img.size
            key = (idx, Wd, Hd)
            changed_full = self.force_full or prev is None or key != prev_key
            self.force_full = False
            if changed_full:
                changed = -1
                tm = None
            else:
                diff = np.any(arr != prev, axis=2)
                th, tw = (Hd + TILE - 1) // TILE, (Wd + TILE - 1) // TILE
                pad = np.zeros((th * TILE, tw * TILE), dtype=bool)
                pad[:Hd, :Wd] = diff
                tm = pad.reshape(th, TILE, tw, TILE).any(axis=(1, 3))
                changed = int(tm.sum())

            use_h264 = self._use_h264()
            codec = "h264" if use_h264 else "jpeg"
            if codec != sent_codec:
                sent_codec = codec
                self.send_json({"t": "codec", "name": codec, "encoder": MEDIA.h264_encoder_name() if use_h264 else ""})
            if use_h264:
                if changed == 0 and settle <= 0:
                    self._sleep_frame(t0)
                    continue
                settle = 8 if changed != 0 else settle - 1  # kilka klatek po zmianie – obraz się „wyostrza”
                ekey = (Wd - Wd % 2, Hd - Hd % 2, self.fps, self.quality)
                try:
                    if enc is None or ekey != enc_key:
                        if enc:
                            enc.close()
                        enc = MEDIA.VideoEncoder(Wd, Hd, self.fps, BITRATES.get(self.quality, 4_000_000))
                        enc_key = ekey
                    if changed_full:
                        enc.force_key = True
                    data, is_key = enc.encode(arr)
                except Exception as e:
                    self.svc.log(f"Koder H.264 nie działa ({e}) – przełączam na JPEG")
                    self.svc.caps["h264"] = False
                    enc = None
                    self.force_full = True
                    continue
                if data:
                    with self.cond:
                        self.inflight += 1
                    try:
                        self.ch.send(M_VIDEO, struct.pack(">IHHB", seq, enc.w, enc.h, 1 if is_key else 0) + data)
                    except Exception:
                        self.stop()
                        break
                    seq += 1
                prev, prev_key = arr, key
                self._sleep_frame(t0)
                continue

            # --- tryb JPEG (kafelki)
            quality = self.quality
            if changed_full:
                rects = [(0, 0, Wd, Hd)]
            elif changed == 0:
                if not refined and time.time() - last_change > 0.8 and quality < 90:
                    rects = [(0, 0, Wd, Hd)]
                    quality = min(92, quality + 35)
                    refined = True
                else:
                    self._sleep_frame(t0)
                    continue
            elif changed > 0.5 * tm.size:
                rects = [(0, 0, Wd, Hd)]
            else:
                rects = []
                th, tw = tm.shape
                for ty in range(th):
                    row = tm[ty]
                    tx = 0
                    while tx < tw:
                        if row[tx]:
                            start = tx
                            while tx < tw and row[tx]:
                                tx += 1
                            x, y = start * TILE, ty * TILE
                            rects.append((x, y, min(Wd, tx * TILE) - x, min(Hd, y + TILE) - y))
                        else:
                            tx += 1
            if quality == self.quality:
                last_change = time.time()
                refined = False
            parts = [struct.pack(">IHHHB", seq, Wd, Hd, len(rects), 0)]
            for (x, y, w, h) in rects:
                bio = io.BytesIO()
                img.crop((x, y, x + w, y + h)).save(bio, "JPEG", quality=quality)
                jpg = bio.getvalue()
                parts.append(struct.pack(">HHHHI", x, y, w, h, len(jpg)))
                parts.append(jpg)
            with self.cond:
                self.inflight += 1
            try:
                self.ch.send(M_FRAME, b"".join(parts))
            except Exception:
                self.stop()
                break
            seq += 1
            prev, prev_key = arr, key
            self._sleep_frame(t0)
        try:
            if sct:
                sct.close()
            if enc:
                enc.close()
        except Exception:
            pass

    def _sleep_frame(self, t0):
        dt = 1.0 / max(1, self.fps) - (time.time() - t0)
        if dt > 0:
            time.sleep(dt)

    # ---------------------------------------------------------------- dźwięk, prywatność
    def _set_audio(self, on):
        if on and self.svc.caps.get("audio"):
            if not self.audio:
                self.audio = MEDIA.AudioStreamer(lambda pkt: self._send_audio(pkt), log=self.svc.log)
            self.audio.start()
        elif self.audio:
            self.audio.stop()

    def _send_audio(self, pkt):
        try:
            self.ch.send(M_AUDIO, pkt)
        except Exception:
            if self.audio:
                self.audio.stop()

    def _set_privacy(self, on, notify=True):
        err = ""
        if on and not self.privacy:
            p = W.PrivacyScreen()
            ok, err = p.start()
            if ok:
                self.privacy = p
                self.blocked = W.block_input(True)  # wątek odbiorczy = wątek wstrzykujący wejście
                self.svc.log("Włączono tryb prywatności" + ("" if self.blocked else
                                                           " (lokalna mysz/klawiatura nie jest zablokowana – brak uprawnień)"))
        elif not on and self.privacy:
            self.privacy.stop()
            self.privacy = None
            if self.blocked:
                W.block_input(False)
                self.blocked = False
        if notify:
            self.send_json({"t": "privacy_state", "on": bool(self.privacy), "blocked": self.blocked, "error": err})

    # ---------------------------------------------------------------- wejście
    def _pos(self, m):
        mon = self.cur_mon
        if not mon:
            return None
        fx = min(max(float(m.get("x", 0)), 0.0), 1.0)
        fy = min(max(float(m.get("y", 0)), 0.0), 1.0)
        return (int(round(mon["left"] + fx * (mon["width"] - 1))), int(round(mon["top"] + fy * (mon["height"] - 1))))

    def _key_obj(self, k):
        if "special" in k:
            return getattr(self.Key, str(k["special"]), None)
        c = k.get("char")
        if isinstance(c, str) and len(c) == 1:
            return self.KeyCode.from_char(c)
        return None

    def _type_text(self, text):
        held = [(i, key) for i, key in self.pressed_keys.items() if key in self.mods]
        for _i, key in held:
            self.kb.release(key)
        try:
            self.kb.type(text)
        finally:
            for _i, key in held:
                self.kb.press(key)

    def _release_all(self):
        if not self.input_ok:
            return
        for key in list(self.pressed_keys.values()):
            try:
                self.kb.release(key)
            except Exception:
                pass
        self.pressed_keys.clear()
        for b in list(self.pressed_buttons):
            try:
                if isinstance(b, str):
                    W.mouse_button(None, None, b, False)
                else:
                    self.mouse.release(b)
            except Exception:
                pass
        self.pressed_buttons.clear()

    def _shortcut(self, name):
        K = self.Key
        if name == "lock" and sys.platform == "win32":
            W.lock_workstation()
            return
        combos = {
            "alt_tab": [K.alt, K.tab], "win": [K.cmd], "task_manager": [K.ctrl, K.shift, K.esc],
            "ctrl_alt_del": [K.ctrl, K.alt, K.delete], "alt_f4": [K.alt, K.f4],
            "win_d": [K.cmd, self.KeyCode.from_char("d")], "win_e": [K.cmd, self.KeyCode.from_char("e")],
            "lock": [K.cmd, self.KeyCode.from_char("l")], "print_screen": [getattr(K, "print_screen", K.f13)],
        }
        keys = combos.get(name)
        if not keys:
            return
        for k in keys:
            self.kb.press(k)
        for k in reversed(keys):
            self.kb.release(k)

    # ---------------------------------------------------------------- wiadomości
    def _handle(self, m):
        t = m.get("t")
        try:
            if t == "ack":
                with self.cond:
                    self.inflight = max(0, self.inflight - 1)
                    self.cond.notify_all()
            elif t == "ping":
                if "ts" in m:
                    self.send_json({"t": "pong", "ts": m["ts"]})
            elif t in ("mouse_move", "mouse_btn", "wheel", "key", "type_text", "shortcut"):
                if self.input_ok:
                    if self.svc.agent_mode:
                        W.sync_input_desktop()
                    self._handle_input(t, m)
            elif t == "clipboard":
                if self.clip and isinstance(m.get("text"), str):
                    self.clip.remote_text(m["text"])
            elif t == "chat":
                text = str(m.get("text", ""))
                if self.svc.on_chat:
                    self.svc.on_chat(self, text)
                else:
                    self.svc.log(f"Wiadomość od {self.client}: {text}")
            elif t == "settings":
                self.fps = int(min(max(int(m.get("fps", self.fps)), 1), 60))
                self.quality = int(min(max(int(m.get("quality", self.quality)), 10), 95))
                self.scale = float(min(max(float(m.get("scale", self.scale)), 0.2), 1.0))
                self.codec_pref = m.get("codec", self.codec_pref)
                self.force_full = True
            elif t == "monitor":
                self.monitor = int(m.get("index", 1))
                self.force_full = True
            elif t == "refresh":
                self.force_full = True
            elif t == "video":
                self.video_on = bool(m.get("on", True))
                self.force_full = True
            elif t == "audio":
                self._set_audio(bool(m.get("on")))
            elif t == "privacy":
                self._set_privacy(bool(m.get("on")))
            elif t == "reboot":
                self.svc.log(f"Zdalny restart zlecony przez {self.client}")
                self.send_json({"t": "rebooting"})
                W.reboot(3)
            elif t == "wol":
                try:
                    send_wol(m.get("mac", ""), m.get("broadcast") or "255.255.255.255")
                    self.send_json({"t": "op_result", "req": m.get("req"), "ok": True})
                except Exception as e:
                    self.send_json({"t": "op_result", "req": m.get("req"), "ok": False, "error": str(e)})
            elif t == "ls":
                threading.Thread(target=self._do_ls, args=(m,), daemon=True).start()
            elif t == "get":
                ev = threading.Event()
                self.cancels[m.get("req")] = ev
                threading.Thread(target=self._do_get, args=(m, ev), daemon=True).start()
            elif t == "get_cancel":
                ev = self.cancels.get(m.get("req"))
                if ev:
                    ev.set()
            elif t in ("mkdir", "delete", "rename"):
                self._do_fsop(m)
            elif t == "file_begin":
                if m.get("clip"):
                    base = CF.ClipboardSync.clip_dir(m["clip"])
                else:
                    dest = m.get("dest")
                    base = dest if dest and os.path.isdir(dest) else downloads_dir()
                try:
                    self.files.begin(m, base)["clip"] = m.get("clip")
                except OSError as e:
                    self.send_json({"t": "file_error", "id": m.get("id"), "error": str(e)})
            elif t == "file_end":
                e = self.files.end(m)
                if e:
                    if not e.get("clip"):
                        self.svc.log(f"Odebrano plik: {e['path']}")
                    self.send_json({"t": "file_saved", "id": m.get("id"), "path": e["path"]})
            elif t == "file_cancel":
                self.files.cancel(m.get("id"))
            elif t == "clip_files_end":
                if self.clip:
                    self.clip.remote_files_end(m)
        except Exception as e:
            self.svc.log(f"Błąd obsługi '{t}': {e}")

    def _check_uipi(self, point=None):
        """Windows nie pozwala zwykłemu programowi sterować oknem uruchomionym jako administrator (UIPI).
        Wykrywamy to i mówimy wprost, co zrobić. Dla kliknięć sprawdzamy okno pod kursorem, dla klawiszy –
        okno na pierwszym planie."""
        now = time.time()
        if sys.platform != "win32" or self.svc.agent_mode or now - self._uipi_check < 1:
            return False
        self._uipi_check = now
        try:
            if W.is_admin():
                return False
            title, elevated = W.window_info_at(*point) if point else W.foreground_info()
        except Exception:
            return False
        if elevated and now - self._uipi_told > 60:
            self._uipi_told = now
            self.svc.log(f"Okno „{title}” działa jako administrator – Windows blokuje jego sterowanie")
            self.send_json({"t": "notice", "kind": "warn", "text":
                            f"Okno „{title[:40]}” na komputerze zdalnym działa jako administrator, więc Windows "
                            "blokuje klikanie w nim. Rozwiązanie: na tamtym komputerze PilotDesk → Dostęp → "
                            "Usługa systemowa → Zainstaluj."})
        return elevated

    def monitors_info(self):
        try:
            import mss
            with mss.mss() as sct:
                return [(m["left"], m["top"], m["width"], m["height"]) for m in sct.monitors]
        except Exception as e:
            return f"? ({e})"

    def _click_failed(self, button, p, err):
        """SendInput odrzucił kliknięcie – zwykle ekran blokady, okno UAC albo program działający jako administrator."""
        _log(f"Kliknięcie {button} w {p} odrzucone przez Windows (SendInput, błąd {err})")
        now = time.time()
        if now - self._click_fail_told < 30:
            return
        self._click_fail_told = now
        why = ("na komputerze zdalnym jest ekran blokady, okno UAC (Kontrola konta użytkownika) albo program "
               "uruchomiony jako administrator") if err == 5 else f"kod błędu {err}"
        self.send_json({"t": "notice", "kind": "warn", "text":
                        f"Windows na komputerze zdalnym zablokował kliknięcie ({why}). Rozwiązanie: na tamtym "
                        "komputerze PilotDesk → Dostęp → Usługa systemowa → Zainstaluj."})

    def _mouse_win(self, t, m):
        """Mysz w Windows: bezpośrednio SendInput – ruch i przycisk w jednym zdarzeniu, z kontrolą wyniku."""
        if t == "mouse_move":
            p = self._pos(m)
            if p:
                W.mouse_move(*p)
        elif t == "mouse_btn":
            b = m.get("b")
            if b not in ("left", "right", "middle"):
                return
            p = self._pos(m)
            down = bool(m.get("down"))
            if down:
                self._check_uipi(p)
            ok, err = W.mouse_button(p[0] if p else None, p[1] if p else None, b, down)
            (self.pressed_buttons.add if down else self.pressed_buttons.discard)(b)
            if self._clicks_logged < 6:
                self._clicks_logged += 1
                _log(f"Mysz: {b} {'wciśnięty' if down else 'puszczony'} w {p} → "
                     f"{'OK' if ok else f'BŁĄD {err}'}")
            if not ok:
                self._click_failed(b, p, err)
        elif t == "wheel":
            W.mouse_wheel(int(m.get("dx", 0)), int(m.get("dy", 0)))

    def _handle_input(self, t, m):
        if t in ("mouse_move", "mouse_btn", "wheel"):
            note_remote_input()
        if t in ("mouse_move", "mouse_btn", "wheel") and self.win_mouse:
            try:
                self._mouse_win(t, m)
                return
            except Exception as e:  # awaryjnie wracamy do pynput
                self.win_mouse = False
                _log(f"Bezpośrednie SendInput niedostępne ({e!r}) – używam pynput")
        if t == "key" and m.get("down"):
            self._check_uipi()
        if t == "mouse_move":
            p = self._pos(m)
            if p:
                self.mouse.position = p
        elif t == "mouse_btn":
            b = {"left": self.Button.left, "right": self.Button.right, "middle": self.Button.middle}.get(m.get("b"))
            if b is None:
                return
            p = self._pos(m)
            if m.get("down"):
                self._check_uipi(p)
            if p:
                self.mouse.position = p
            if m.get("down"):
                self.mouse.press(b)
                self.pressed_buttons.add(b)
            else:
                self.mouse.release(b)
                self.pressed_buttons.discard(b)
        elif t == "wheel":
            self.mouse.scroll(int(m.get("dx", 0)), int(m.get("dy", 0)))
        elif t == "key":
            k = m.get("k") or {}
            if "text" in k:
                if m.get("down") and isinstance(k["text"], str):
                    self._type_text(k["text"])
                return
            key = self._key_obj(k)
            if key is None:
                return
            ident = json.dumps(k, sort_keys=True)
            if m.get("down"):
                self.kb.press(key)
                self.pressed_keys[ident] = key
            else:
                self.kb.release(self.pressed_keys.pop(ident, key))
        elif t == "type_text":
            txt = m.get("text", "")
            if isinstance(txt, str):
                self._type_text(txt)
        elif t == "shortcut":
            self._shortcut(m.get("name"))

    def _do_ls(self, m):
        try:
            r = list_dir(m.get("path", ""))
            self.send_json({"t": "ls_result", "req": m.get("req"), **r})
        except Exception as e:
            self.send_json({"t": "ls_result", "req": m.get("req"), "path": m.get("path", ""), "error": str(e),
                            "entries": []})

    def _do_get(self, m, ev):
        req = m.get("req")
        try:
            for full, rel in iter_path_files(m.get("path", "")):
                if ev.is_set() or not self.running:
                    break
                send_file(self.ch, full, rel, extra={"req": req}, cancel=ev)
        except Exception as e:
            self.send_json({"t": "get_error", "req": req, "error": str(e)})
        finally:
            self.cancels.pop(req, None)
            self.send_json({"t": "get_done", "req": req})

    def _do_fsop(self, m):
        t = m["t"]
        path = m.get("path", "")
        try:
            if t == "mkdir":
                os.makedirs(path, exist_ok=False)
            elif t == "delete":
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            elif t == "rename":
                os.rename(path, m.get("new", ""))
            self.send_json({"t": "op_result", "req": m.get("req"), "ok": True})
        except Exception as e:
            self.send_json({"t": "op_result", "req": m.get("req"), "ok": False, "error": str(e)})
