"""PilotDesk – wspólne elementy: protokół, szyfrowanie, konfiguracja, przesyłanie plików.

Protokół (TCP):
  1. Host wysyła jawny "hello" (sól hasła, nonce).
  2. Klient odpowiada swoim nonce.
  3. Obie strony liczą klucze sesji: scrypt(hasło, sól) -> HKDF(nonce_h + nonce_k).
  4. Dalej każda ramka jest szyfrowana AES-256-GCM (osobny klucz w każdą stronę,
     licznik jako nonce -> ochrona przed powtórzeniem/podmianą ramek).
Hasło nigdy nie jest przesyłane. Serwer pośredniczący (relay) widzi tylko szyfrogram.
"""
import base64
import hashlib
import hmac
import json
import os
import platform
import secrets
import socket
import string
import struct
import sys
import threading
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

APP_NAME = "PilotDesk"
VERSION = "3.7"
DEFAULT_UPDATE_SOURCE = "karoljurmanowicz/pilotdesk"  # GitHub: właściciel/repozytorium (zakładka Releases)
PROTO = 2
DEFAULT_PORT = 47800        # połączenia bezpośrednie (LAN / VPN / przekierowanie portu)
DEFAULT_RELAY_PORT = 47900  # serwer pośredniczący
CHUNK = 64 * 1024           # rozmiar kawałka pliku
MAX_MSG = 64 * 1024 * 1024
MAX_PLAIN = 64 * 1024
AUTH_MAGIC = "pilotdesk-auth-v2"

# Kiedy ostatnio zdalna sesja poruszyła myszą tego komputera. Wspólna mysz (pd_kvm.EdgeSwitch) nie może brać
# takich ruchów za ruch fizycznej myszy – inaczej przełączała się na drugi komputer i połykała kliknięcia.
REMOTE_INPUT = {"t": 0.0}


def note_remote_input():
    REMOTE_INPUT["t"] = time.time()


def remote_input_recent(window=1.0):
    return time.time() - REMOTE_INPUT["t"] < window

# typy wiadomości wewnątrz zaszyfrowanego kanału
M_JSON, M_FRAME, M_FILE, M_VIDEO, M_AUDIO = 1, 2, 3, 4, 5


class AuthError(Exception):
    pass


class ProtocolError(Exception):
    pass


# --------------------------------------------------------------------------- konfiguracja

def config_path():
    return os.environ.get("PILOTDESK_CONFIG") or os.path.join(os.path.expanduser("~"), ".pilotdesk.json")


def machine_dir():
    return os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "PilotDesk")


def machine_config_path():
    """Konfiguracja udostępniania w trybie usługi Windows (wspólna dla usługi i programu)."""
    return os.path.join(machine_dir(), "host.json")


def service_mode():
    return sys.platform == "win32" and os.path.exists(machine_config_path())


def host_config_path():
    return machine_config_path() if service_mode() else config_path()


def load_config(path=None):
    try:
        with open(path or config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_cfg_lock = threading.Lock()


def save_config(cfg, path=None):
    with _cfg_lock:
        p = path or config_path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, p)


def b64e(b):
    return base64.b64encode(b).decode("ascii")


def b64d(s):
    return base64.b64decode(s.encode("ascii"))


def ensure_host_identity(cfg):
    """Nadaje komputerowi stały 9-cyfrowy ID i sekret do rejestracji na serwerze."""
    changed = False
    if not cfg.get("host_id"):
        cfg["host_id"] = str(secrets.randbelow(900_000_000) + 100_000_000)
        changed = True
    if not cfg.get("id_secret"):
        cfg["id_secret"] = secrets.token_hex(32)
        changed = True
    for k, v in (("listen_port", DEFAULT_PORT), ("direct_enabled", True), ("relay", ""),
                 ("relay_key", ""), ("book", []), ("ask_enabled", True)):
        if k not in cfg:
            cfg[k] = v
            changed = True
    return changed


def format_id(i):
    i = str(i)
    return " ".join(i[k:k + 3] for k in range(0, len(i), 3))


def derive_password_key(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 15, r=8, p=1,
                          maxmem=128 * 1024 * 1024, dklen=32)


def set_host_password(cfg, password):
    """Zapisuje tylko pochodną hasła (scrypt), nie samo hasło."""
    salt = secrets.token_bytes(16)
    cfg["pw_salt"] = b64e(salt)
    cfg["pw_key"] = b64e(derive_password_key(password, salt))


def update_source(cfg):
    """Źródło aktualizacji: ustawione przez użytkownika albo domyślne repozytorium projektu."""
    v = cfg.get("update_source")
    return DEFAULT_UPDATE_SOURCE if v is None else v


def has_password(cfg):
    return bool(cfg.get("pw_salt") and cfg.get("pw_key"))


def hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "komputer"


def username():
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "user"


def get_mac():
    """Adres MAC głównej karty sieciowej (do Wake-on-LAN)."""
    import uuid
    node = uuid.getnode()
    if (node >> 40) & 1:  # losowy adres – brak prawdziwej karty
        return ""
    return ":".join(f"{(node >> s) & 0xff:02x}" for s in range(40, -1, -8))


def send_wol(mac, broadcast="255.255.255.255"):
    """Wysyła „magiczny pakiet” Wake-on-LAN."""
    raw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(raw) != 6:
        raise ValueError("nieprawidłowy adres MAC")
    pkt = b"\xff" * 6 + raw * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        for port in (9, 7):
            s.sendto(pkt, (broadcast, port))
    finally:
        s.close()


_ips_cache = {"ips": None, "t": 0.0, "busy": False}


def _primary_ip():
    """Adres głównej karty sieciowej – bez zapytań DNS (natychmiast)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _refresh_ips():
    ips = []
    p = _primary_ip()
    if p:
        ips.append(p)
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:  # bywa wolne przy zepsutym DNS
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    _ips_cache.update(ips=ips or ["127.0.0.1"], t=time.time(), busy=False)


def get_local_ips():
    """Adresy IP tego komputera. Nigdy nie blokuje: wolniejsze ustalanie odbywa się w tle, a do tego czasu
    zwracamy adres głównej karty sieciowej."""
    c = _ips_cache
    if c["ips"] is None or time.time() - c["t"] > 60:
        if not c["busy"]:
            c["busy"] = True
            threading.Thread(target=_refresh_ips, name="local-ips", daemon=True).start()
        if c["ips"] is None:
            p = _primary_ip()
            return [p] if p else ["127.0.0.1"]
    return list(c["ips"])


# --------------------------------------------------------------------------- gniazda

def recv_exact(sock, n):
    buf = bytearray(n)
    view = memoryview(buf)
    pos = 0
    while pos < n:
        r = sock.recv_into(view[pos:], n - pos)
        if r == 0:
            raise ConnectionError("Połączenie zostało zamknięte")
        pos += r
    return buf


def send_plain(sock, obj):
    data = json.dumps(obj).encode("utf-8")
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_plain(sock):
    (n,) = struct.unpack(">I", recv_exact(sock, 4))
    if n > MAX_PLAIN:
        raise ProtocolError("Za duża wiadomość powitalna")
    return json.loads(bytes(recv_exact(sock, n)).decode("utf-8"))


def send_line(sock, obj):
    sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))


def recv_line(sock, limit=16384):
    """Czyta jedną linię JSON bajt po bajcie (żeby nie zjeść danych, które przyjdą później)."""
    buf = bytearray()
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("Serwer zamknął połączenie")
        if b == b"\n":
            return json.loads(buf.decode("utf-8"))
        buf += b
        if len(buf) > limit:
            raise ProtocolError("Za długa linia")


def tune_socket(sock):
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass


def open_tcp(host, port, timeout=10):
    sock = socket.create_connection((host, port), timeout=timeout)
    tune_socket(sock)
    return sock


def parse_hostport(s, default_port):
    s = s.strip()
    if s.startswith("["):  # [IPv6]:port
        host, _, rest = s[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    elif s.count(":") == 1:
        host, port = s.split(":")
    else:
        host, port = s, ""
    return host, (int(port) if port else default_port)


def parse_target(s):
    """'123 456 789' -> ('id', '123456789');  '192.168.1.5[:port]' -> ('direct', host, port)."""
    t = s.replace(" ", "").strip()
    if t.isdigit() and 6 <= len(t) <= 12:
        return ("id", t)
    host, port = parse_hostport(t, DEFAULT_PORT)
    return ("direct", host, port)


def relay_connect_viewer(relay_addr, relay_key, host_id):
    h, p = parse_hostport(relay_addr, DEFAULT_RELAY_PORT)
    sock = open_tcp(h, p)
    sock.settimeout(30)
    send_line(sock, {"op": "connect", "id": host_id, "key": relay_key or ""})
    r = recv_line(sock)
    if not r.get("ok"):
        sock.close()
        raise ConnectionError(r.get("error", "Serwer pośredniczący odmówił połączenia"))
    return sock


# --------------------------------------------------------------------------- kryptografia

def hkdf(key, salt, info, length):
    prk = hmac.new(salt, key, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


class SecureChannel:
    """Zaszyfrowany kanał ramek. send() jest bezpieczne wątkowo, recv() woła jeden wątek."""

    def __init__(self, sock, send_key, recv_key):
        self.sock = sock
        self._enc = AESGCM(send_key)
        self._dec = AESGCM(recv_key)
        self._sctr = 0
        self._rctr = 0
        self._lock = threading.Lock()
        self.closed = False
        self.bytes_out = 0
        self.bytes_in = 0

    def send(self, mtype, payload=b""):
        with self._lock:
            if self.closed:
                raise ConnectionError("Kanał zamknięty")
            nonce = struct.pack(">IQ", 0, self._sctr)
            self._sctr += 1
            ct = self._enc.encrypt(nonce, bytes([mtype]) + payload, None)
            self.sock.sendall(struct.pack(">I", len(ct)) + ct)
            self.bytes_out += len(ct) + 4

    def send_json(self, obj):
        self.send(M_JSON, json.dumps(obj).encode("utf-8"))

    def recv(self):
        (n,) = struct.unpack(">I", recv_exact(self.sock, 4))
        if n > MAX_MSG or n < 17:
            raise ProtocolError("Nieprawidłowa długość ramki")
        ct = recv_exact(self.sock, n)
        nonce = struct.pack(">IQ", 0, self._rctr)
        self._rctr += 1
        pt = self._dec.decrypt(nonce, bytes(ct), None)
        self.bytes_in += n + 4
        return pt[0], pt[1:]

    def close(self):
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


ZERO_KEY = bytes(32)


def device_key(cfg):
    """Stały klucz tego komputera (Ed25519) – pozwala „zapamiętać” go na innych komputerach."""
    from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat
    if not cfg.get("device_key"):
        k = Ed25519PrivateKey.generate()
        cfg["device_key"] = b64e(k.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    return Ed25519PrivateKey.from_private_bytes(b64d(cfg["device_key"]))


def device_pub(cfg):
    return b64e(device_key(cfg).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def _transcript(hn, vn, hpub, vpub):
    return b"pilotdesk-device-v1" + hn + vn + hpub + vpub


def _pub_bytes(priv):
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _derive(shared, pw_key, hn, vn, hpub, vpub):
    k = hkdf(shared + pw_key, hn + vn + hpub + vpub, b"pilotdesk v2 session keys", 96)
    code = int.from_bytes(hashlib.sha256(k[64:]).digest()[:4], "big") % 1_000_000
    return k[:32], k[32:64], f"{code:06d}"  # host->viewer, viewer->host, kod weryfikacyjny


def host_handshake(sock, cfg, info, ask_cb=None):
    """Zwraca (kanał, dane klienta, tryb). ask_cb(klient, kod, klucz_urządzenia|None) -> True/False (tryb bez hasła)."""
    has_pw = has_password(cfg)
    salt = b64d(cfg["pw_salt"]) if has_pw else secrets.token_bytes(16)
    pw_key = b64d(cfg["pw_key"]) if has_pw else secrets.token_bytes(32)
    ask_ok = bool(cfg.get("ask_enabled", True)) and ask_cb is not None
    priv = X25519PrivateKey.generate()
    hpub = _pub_bytes(priv)
    hn = secrets.token_bytes(16)
    send_plain(sock, {"app": APP_NAME, "proto": PROTO, "salt": b64e(salt), "nonce": b64e(hn), "pub": b64e(hpub),
                      "name": info.get("name", ""), "pw": has_pw, "ask": ask_ok})
    m = recv_plain(sock)
    if m.get("app") != APP_NAME:
        raise ProtocolError("Nieznany klient")
    if m.get("proto") != PROTO:
        raise ProtocolError("Inna wersja programu po drugiej stronie")
    vn, vpub = b64d(m.get("nonce", "")), b64d(m.get("pub", ""))
    if len(vn) != 16 or len(vpub) != 32:
        raise ProtocolError("Zły nonce/klucz")
    mode = "ask" if m.get("mode") == "ask" else "password"
    shared = priv.exchange(X25519PublicKey.from_public_bytes(vpub))
    h2v, v2h, code = _derive(shared, pw_key if mode == "password" else ZERO_KEY, hn, vn, hpub, vpub)
    ch = SecureChannel(sock, send_key=h2v, recv_key=v2h)
    try:
        _t, body = ch.recv()
        auth = json.loads(body)
    except (InvalidTag, ValueError):
        raise AuthError("Błędne hasło")
    if auth.get("t") != "auth" or auth.get("magic") != AUTH_MAGIC:
        raise AuthError("Błędne hasło")
    dev = None
    try:
        if auth.get("device_pub") and auth.get("device_sig"):
            Ed25519PublicKey.from_public_bytes(b64d(auth["device_pub"])).verify(
                b64d(auth["device_sig"]), _transcript(hn, vn, hpub, vpub))
            dev = auth["device_pub"]
    except Exception:
        dev = None
    if mode == "ask":
        if not ask_ok:
            ch.send_json({"t": "auth_denied", "reason": "Ten komputer przyjmuje tylko połączenia z hasłem."})
            raise PermissionError("tryb bez hasła wyłączony")
        ch.send_json({"t": "waiting", "code": code})
        if not ask_cb(str(auth.get("client", "?"))[:80], code, dev):
            ch.send_json({"t": "auth_denied", "reason": "Połączenie zostało odrzucone na zdalnym komputerze."})
            raise PermissionError("odrzucono")
    ch.send_json({"t": "auth_ok", "mode": mode, **info})
    return ch, auth, mode


def viewer_handshake(sock, key_provider, client_info, mode="password", on_code=None, dev_key=None):
    """key_provider(salt) -> klucz hasła; w trybie 'ask' nie jest wołany. on_code(kod) – kod weryfikacyjny."""
    hello = recv_plain(sock)
    if hello.get("app") != APP_NAME:
        raise ProtocolError("Po drugiej stronie nie działa PilotDesk")
    if hello.get("proto") != PROTO:
        raise ProtocolError("Druga strona ma inną wersję PilotDesk – zaktualizuj program na obu komputerach.")
    if mode == "ask" and not hello.get("ask"):
        raise AuthError("Ten komputer wymaga hasła (połączenia bez hasła są na nim wyłączone).")
    salt, hn, hpub = b64d(hello["salt"]), b64d(hello["nonce"]), b64d(hello["pub"])
    pw_key = key_provider(salt) if mode == "password" else ZERO_KEY
    priv = X25519PrivateKey.generate()
    vpub = _pub_bytes(priv)
    vn = secrets.token_bytes(16)
    send_plain(sock, {"app": APP_NAME, "proto": PROTO, "nonce": b64e(vn), "pub": b64e(vpub), "mode": mode})
    shared = priv.exchange(X25519PublicKey.from_public_bytes(hpub))
    h2v, v2h, code = _derive(shared, pw_key, hn, vn, hpub, vpub)
    ch = SecureChannel(sock, send_key=v2h, recv_key=h2v)
    auth = {"t": "auth", "magic": AUTH_MAGIC, "mode": mode, **client_info}
    if dev_key is not None:
        auth["device_pub"] = b64e(dev_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
        auth["device_sig"] = b64e(dev_key.sign(_transcript(hn, vn, hpub, vpub)))
    ch.send_json(auth)
    while True:
        try:
            _t, body = ch.recv()
            msg = json.loads(body)
        except (InvalidTag, ConnectionError, OSError, ValueError):
            raise AuthError("Błędne hasło (albo komputer odrzucił połączenie)")
        if msg.get("t") == "waiting":
            if on_code:
                on_code(msg.get("code", code))
            sock.settimeout(90)
            continue
        if msg.get("t") == "auth_denied":
            raise AuthError(msg.get("reason", "Odrzucono połączenie"))
        if msg.get("t") != "auth_ok":
            raise AuthError("Błędne hasło")
        return ch, hello, msg, (pw_key if mode == "password" else None)


# --------------------------------------------------------------------------- pliki

def downloads_dir():
    home = os.path.expanduser("~")
    for n in ("Downloads", "Pobrane"):
        d = os.path.join(home, n)
        if os.path.isdir(d):
            return os.path.join(d, "PilotDesk")
    return os.path.join(home, "PilotDesk")


def safe_rel_path(rel):
    parts = []
    for p in rel.replace("\\", "/").split("/"):
        p = p.strip().replace(":", "_")
        if p in ("", ".", ".."):
            continue
        parts.append(p)
    return os.path.join(*parts) if parts else "plik"


def unique_path(path):
    if not os.path.exists(path) and not os.path.exists(path + ".part"):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = f"{base} ({i}){ext}"
        if not os.path.exists(cand) and not os.path.exists(cand + ".part"):
            return cand
        i += 1


def human_size(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


class FileReceiver:
    """Odbiór plików. Wszystkie metody wołać z jednego wątku (odbiorczego)."""

    def __init__(self):
        self.files = {}

    def begin(self, msg, base_dir):
        tid = msg["id"]
        rel = safe_rel_path(msg.get("rel") or "plik")
        path = unique_path(os.path.join(base_dir, rel))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        f = open(path + ".part", "wb")
        e = {"f": f, "path": path, "size": int(msg.get("size", 0)), "got": 0, "name": rel,
             "last": 0.0}
        self.files[tid] = e
        return e

    def chunk(self, payload):
        tid = bytes(payload[:16]).hex()
        e = self.files.get(tid)
        if not e:
            return None
        e["f"].write(payload[16:])
        e["got"] += len(payload) - 16
        return tid, e

    def end(self, msg):
        e = self.files.pop(msg.get("id"), None)
        if not e:
            return None
        e["f"].close()
        os.replace(e["path"] + ".part", e["path"])
        return e

    def cancel(self, tid):
        e = self.files.pop(tid, None)
        if e:
            try:
                e["f"].close()
                os.remove(e["path"] + ".part")
            except OSError:
                pass
        return e

    def close_all(self):
        for tid in list(self.files):
            self.cancel(tid)


def iter_path_files(path):
    """Zwraca (pełna_ścieżka, ścieżka_względna) dla pliku albo wszystkich plików w folderze."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        parent = os.path.dirname(path.rstrip("\\/")) or path
        for root, _dirs, files in os.walk(path):
            for fn in files:
                full = os.path.join(root, fn)
                yield full, os.path.relpath(full, parent).replace(os.sep, "/")
    else:
        yield path, os.path.basename(path)


def send_file(ch, path, rel, extra=None, progress=None, cancel=None):
    tid = secrets.token_bytes(16)
    hexid = tid.hex()
    size = os.path.getsize(path)
    ch.send_json({"t": "file_begin", "id": hexid, "rel": rel, "size": size, **(extra or {})})
    sent = 0
    last = 0.0
    if progress:
        progress(hexid, rel, 0, size, "trwa")
    try:
        with open(path, "rb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    ch.send_json({"t": "file_cancel", "id": hexid})
                    if progress:
                        progress(hexid, rel, sent, size, "anulowano")
                    return False
                data = f.read(CHUNK)
                if not data:
                    break
                ch.send(M_FILE, tid + data)
                sent += len(data)
                now = time.time()
                if progress and now - last > 0.25:
                    last = now
                    progress(hexid, rel, sent, size, "trwa")
    except OSError as e:
        try:
            ch.send_json({"t": "file_cancel", "id": hexid})
        except Exception:
            pass
        if progress:
            progress(hexid, rel, sent, size, f"błąd: {e}")
        return False
    ch.send_json({"t": "file_end", "id": hexid})
    if progress:
        progress(hexid, rel, size, size, "wysłano")
    return True


def list_roots():
    home = os.path.expanduser("~")
    out = []
    if sys.platform == "win32":
        for L in string.ascii_uppercase:
            d = f"{L}:\\"
            if os.path.exists(d):
                out.append({"name": d, "path": d, "dir": True, "size": 0, "mtime": 0})
    else:
        out.append({"name": "/", "path": "/", "dir": True, "size": 0, "mtime": 0})
    for n in ("", "Desktop", "Pulpit", "Documents", "Dokumenty", "Downloads", "Pobrane"):
        d = os.path.join(home, n) if n else home
        if os.path.isdir(d):
            out.append({"name": ("🏠 " + os.path.basename(d)) if n == "" else n, "path": d,
                        "dir": True, "size": 0, "mtime": 0})
    return out


def list_dir(path, limit=10000):
    """Lista katalogu. Pusta ścieżka = dyski / foldery startowe."""
    if not path:
        return {"path": "", "parent": "", "entries": list_roots()}
    path = os.path.abspath(os.path.expanduser(path))
    entries = []
    with os.scandir(path) as it:
        for e in it:
            try:
                is_dir = e.is_dir()
                st = e.stat()
                entries.append({"name": e.name, "path": os.path.join(path, e.name), "dir": is_dir,
                                "size": 0 if is_dir else st.st_size, "mtime": int(st.st_mtime)})
            except OSError:
                continue
            if len(entries) >= limit:
                break
    entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    parent = os.path.dirname(path.rstrip("\\/"))
    if parent == path or not parent or path in ("/",) or (len(path) <= 3 and path.endswith(":\\")):
        parent = ""
    return {"path": path, "parent": parent, "entries": entries}
