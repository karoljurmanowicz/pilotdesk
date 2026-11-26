"""PilotDesk – wyszukiwanie komputerów po ID bez serwera.

Każdy komputer z włączonym dostępem odpowiada na zapytania UDP (port 47802). Pytamy:
  * całą sieć lokalną (rozgłoszenie),
  * komputery w Tailscale (lista z `tailscale status --json`, jeśli Tailscale jest zainstalowany),
  * adresy, pod którymi dany komputer był ostatnio widziany.
Dzięki temu wpisujesz tylko ID – adres IP i port znajdują się same.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

DISCOVERY_PORT = 47802
MAGIC = "pilotdesk-discovery-1"


class Responder:
    """Strona udostępniająca: odpowiada „tu jestem” (ID, nazwa, port)."""

    def __init__(self, info_fn):
        self.info_fn = info_fn  # -> dict albo None (gdy nie odpowiadać)
        self.sock = None
        self.running = False

    def start(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", DISCOVERY_PORT))
        except OSError:
            return False
        self.sock = s
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048)
                m = json.loads(data.decode("utf-8"))
                if m.get("magic") != MAGIC:
                    continue
                info = self.info_fn()
                if not info:
                    continue
                if m.get("id") and m["id"] != info["id"]:
                    continue
                self.sock.sendto(json.dumps({"magic": MAGIC, "op": "here", **info}).encode("utf-8"), addr)
            except OSError:
                if not self.running:
                    return
            except Exception:
                continue


def _broadcast_targets():
    from pd_common import get_local_ips
    out = {"255.255.255.255"}
    for ip in get_local_ips():
        p = ip.split(".")
        if len(p) == 4 and not ip.startswith("127.") and not ip.startswith("100."):
            out.add(".".join(p[:3] + ["255"]))
    return out


def tailscale_peers():
    """Adresy włączonych komputerów w Tailscale (pusta lista, gdy Tailscale nie jest zainstalowany)."""
    exe = shutil.which("tailscale")
    if not exe and sys.platform == "win32":
        p = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe")
        exe = p if os.path.exists(p) else None
    if not exe and sys.platform == "darwin":
        p = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
        exe = p if os.path.exists(p) else None
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "status", "--json"], capture_output=True, timeout=3,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
        d = json.loads(r.stdout.decode("utf-8", "replace"))
        out = []
        for peer in (d.get("Peer") or {}).values():
            if peer.get("Online") and peer.get("TailscaleIPs"):
                ip4 = [i for i in peer["TailscaleIPs"] if "." in i]
                if ip4:
                    out.append(ip4[0])
        return out
    except Exception:
        return []


def discover(want_id=None, timeout=1.2, extra=(), exclude_id=None):
    """Zwraca {id: {"ip", "port", "name", "os", "via"}}. Gdy podano want_id – kończy po znalezieniu."""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.15)
    q = {"magic": MAGIC, "op": "find" if want_id else "discover"}
    if want_id:
        q["id"] = want_id
    payload = json.dumps(q).encode("utf-8")
    targets = [(t, "sieć lokalna") for t in _broadcast_targets()]
    targets += [(ip, "zapamiętany adres") for ip in extra if ip]
    ts = []
    tst = threading.Thread(target=lambda: ts.extend(tailscale_peers()), daemon=True)
    tst.start()
    via_of = {}

    def send_all(lst):
        for ip, via in lst:
            via_of.setdefault(ip, via)
            try:
                s.sendto(payload, (ip, DISCOVERY_PORT))
            except OSError:
                pass

    send_all(targets)
    end = time.time() + timeout
    ts_sent = False
    resent = False
    while time.time() < end:
        if not ts_sent and not tst.is_alive():
            ts_sent = True
            send_all([(ip, "Tailscale") for ip in ts])
        if not resent and time.time() > end - timeout / 2:  # UDP bywa gubiony – wysyłamy drugi raz
            resent = True
            send_all(targets)
        try:
            data, addr = s.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            m = json.loads(data.decode("utf-8"))
        except Exception:
            continue
        if m.get("magic") != MAGIC or m.get("op") != "here" or not m.get("id"):
            continue
        if exclude_id and m["id"] == exclude_id:
            continue
        ip = addr[0]
        prev = found.get(m["id"])
        via = "Tailscale" if ip.startswith("100.") else via_of.get(ip, "sieć lokalna")
        # wolimy adres z sieci lokalnej (szybszy) od Tailscale
        if not prev or (prev["ip"].startswith("100.") and not ip.startswith("100.")):
            found[m["id"]] = {"ip": ip, "port": int(m.get("port", 47800)), "name": m.get("name", ""),
                              "os": m.get("os", ""), "via": via}
        if want_id and want_id in found and not found[want_id]["ip"].startswith("100."):
            break
        if want_id and want_id in found and time.time() > end - timeout * 0.6:
            break
    s.close()
    return found
