#!/usr/bin/env python3
"""PilotDesk – serwer pośredniczący (relay).

Uruchom go na dowolnym serwerze z publicznym IP (VPS za kilka zł/mies., Raspberry Pi z
przekierowanym portem itp.). Komputery rejestrują się na nim swoim ID, a przeglądarka łączy się
po ID – bez przekierowywania portów u Ciebie w domu/pracy i bez żadnych limitów.

Serwer tylko przekazuje bajty: cała sesja jest szyfrowana end-to-end hasłem komputera,
więc serwer nie widzi ekranu, plików ani schowka.

Wymaga wyłącznie Pythona 3.8+ (bez dodatkowych bibliotek):
    python3 pd_relay.py --port 47900 --key MOJ_TAJNY_KLUCZ
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time

ID_DB_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "relay_ids.json")


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


class Relay:
    def __init__(self, key, db_path):
        self.key = key or ""
        self.db_path = db_path
        self.hosts = {}      # id -> (writer, lock)
        self.pending = {}    # session -> (host_id, future)
        self.rate = {}       # ip -> [czasy]
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                self.db = json.load(f)
        except Exception:
            self.db = {}

    def save_db(self):
        tmp = self.db_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.db, f)
        os.replace(tmp, self.db_path)

    def rate_ok(self, ip, limit=60):
        now = time.time()
        lst = [t for t in self.rate.get(ip, []) if now - t < 60]
        lst.append(now)
        self.rate[ip] = lst
        if len(self.rate) > 10000:
            self.rate.clear()
        return len(lst) <= limit

    @staticmethod
    async def reply(writer, obj):
        writer.write((json.dumps(obj) + "\n").encode())
        await writer.drain()

    async def handle(self, reader, writer):
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else "?"
        keep_open = False
        try:
            if not self.rate_ok(ip):
                return
            line = await asyncio.wait_for(reader.readline(), 15)
            msg = json.loads(line or b"{}")
            if self.key and not hmac.compare_digest(str(msg.get("key", "")), self.key):
                await self.reply(writer, {"ok": False, "error": "zły klucz serwera (relay_key)"})
                return
            op = msg.get("op")
            if op == "register":
                await self.on_register(msg, reader, writer, ip)
            elif op == "connect":
                await self.on_connect(msg, reader, writer, ip)
            elif op == "accept":
                keep_open = await self.on_accept(msg, reader, writer)
        except Exception:
            pass
        finally:
            if not keep_open:
                try:
                    writer.close()
                except Exception:
                    pass

    def check_secret(self, hid, secret):
        h = hashlib.sha256(secret.encode()).hexdigest()
        stored = self.db.get(hid)
        return stored is not None and hmac.compare_digest(stored, h)

    async def on_register(self, msg, reader, writer, ip):
        hid = str(msg.get("id", ""))
        secret = str(msg.get("secret", ""))
        if not (hid.isdigit() and 6 <= len(hid) <= 12 and len(secret) >= 16):
            await self.reply(writer, {"ok": False, "error": "nieprawidłowe ID"})
            return
        if hid not in self.db:
            self.db[hid] = hashlib.sha256(secret.encode()).hexdigest()
            self.save_db()
        elif not self.check_secret(hid, secret):
            await self.reply(writer, {"ok": False, "error": "to ID należy do innego komputera"})
            return
        old = self.hosts.get(hid)
        if old:
            try:
                old[0].close()
            except Exception:
                pass
        lock = asyncio.Lock()
        self.hosts[hid] = (writer, lock)
        await self.reply(writer, {"ok": True})
        log(f"Komputer {hid} online ({ip})")
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), 120)
                if not line:
                    break
                m = json.loads(line)
                if m.get("op") == "ping":
                    async with lock:
                        await self.reply(writer, {"op": "pong"})
        except Exception:
            pass
        finally:
            if self.hosts.get(hid, (None,))[0] is writer:
                del self.hosts[hid]
                log(f"Komputer {hid} offline")

    async def on_connect(self, msg, reader, writer, ip):
        hid = str(msg.get("id", ""))
        entry = self.hosts.get(hid)
        if not entry:
            await self.reply(writer, {"ok": False, "error": "komputer o tym ID jest offline"})
            return
        hwriter_ctl, lock = entry
        sid = secrets.token_hex(16)
        fut = asyncio.get_running_loop().create_future()
        self.pending[sid] = (hid, fut)
        try:
            async with lock:
                await self.reply(hwriter_ctl, {"op": "incoming", "session": sid})
            hreader, hwriter, done = await asyncio.wait_for(fut, 20)
        except Exception:
            await self.reply(writer, {"ok": False, "error": "komputer nie odpowiada"})
            return
        finally:
            self.pending.pop(sid, None)
        log(f"Sesja do {hid} od {ip}")
        try:
            await self.reply(writer, {"ok": True})
            await self.pipe(reader, writer, hreader, hwriter)
        finally:
            done.set()
            log(f"Koniec sesji do {hid}")

    async def on_accept(self, msg, reader, writer):
        sid = str(msg.get("session", ""))
        p = self.pending.get(sid)
        if not p or p[1].done() or p[0] != str(msg.get("id")) or \
                not self.check_secret(p[0], str(msg.get("secret", ""))):
            await self.reply(writer, {"ok": False, "error": "nieznana sesja"})
            return False
        await self.reply(writer, {"ok": True})
        done = asyncio.Event()
        p[1].set_result((reader, writer, done))
        await done.wait()
        return True  # połączenie zamyka pipe()

    @staticmethod
    async def pipe(r1, w1, r2, w2):
        async def cp(r, w):
            try:
                while True:
                    d = await r.read(256 * 1024)
                    if not d:
                        break
                    w.write(d)
                    await w.drain()
            except Exception:
                pass
            finally:
                try:
                    w.close()
                except Exception:
                    pass
        await asyncio.gather(cp(r1, w2), cp(r2, w1))


async def main():
    ap = argparse.ArgumentParser(description="PilotDesk – serwer pośredniczący")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=47900)
    ap.add_argument("--key", default=os.environ.get("PILOTDESK_RELAY_KEY", ""),
                    help="klucz dostępu do serwera (zalecany; ten sam wpisz w programie)")
    ap.add_argument("--db", default=ID_DB_DEFAULT, help="plik z zarejestrowanymi ID")
    a = ap.parse_args()
    relay = Relay(a.key, a.db)
    server = await asyncio.start_server(relay.handle, a.host, a.port)
    log(f"Serwer pośredniczący PilotDesk działa na {a.host}:{a.port}"
        + (" (z kluczem)" if a.key else " (BEZ klucza – każdy może go używać)"))
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
