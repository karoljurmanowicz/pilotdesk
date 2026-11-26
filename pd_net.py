"""PilotDesk – odporne pobieranie przez HTTPS (aktualizacje).

Problemy, które obchodzi, a które przeglądarka zwykle omija sama:
  * certyfikaty – w Windows weryfikujemy certyfikat systemowo (truststore -> CryptoAPI, która sama dociąga
    brakujące certyfikaty główne); zapasowo pakiet certifi,
  * DNS – gdy systemowy DNS nie odpowiada (np. druga karta sieciowa do drukarki bez internetu ma własny DNS),
    pytamy bezpośrednio publiczne serwery DNS (Cloudflare, Google, Quad9),
  * proxy ustawione w systemie (ustawienia internetowe Windows / zmienne HTTPS_PROXY).
Błędy są tłumaczone na zrozumiały komunikat (NetError.friendly).
"""
import http.client
import json
import os
import random
import socket
import ssl
import struct
import urllib.parse
import urllib.request

UA = "PilotDesk-updater"
PUBLIC_DNS = ("1.1.1.1", "8.8.8.8", "9.9.9.9", "1.0.0.1")


class NetError(Exception):
    def __init__(self, friendly, detail=""):
        super().__init__(f"{friendly} ({detail})" if detail else friendly)
        self.friendly = friendly
        self.detail = detail


# --------------------------------------------------------------------------- TLS

_ctx = None


def ssl_context():
    global _ctx
    if _ctx is not None:
        return _ctx
    ctx = None
    try:
        import truststore  # weryfikacja przez system operacyjny (Windows CryptoAPI / macOS / Linux)
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        ctx = None
    if ctx is None:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except Exception:
            pass
    _ctx = ctx
    return ctx


def _certifi_context():
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


# --------------------------------------------------------------------------- DNS

def _dns_query(name, server, timeout=2.5):
    """Minimalne zapytanie DNS (rekord A) wprost do serwera DNS przez UDP."""
    tid = random.randint(0, 0xFFFF)
    q = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    for part in name.rstrip(".").split("."):
        q += bytes([len(part)]) + part.encode("ascii")
    q += b"\x00" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(q, (server, 53))
        data, _ = s.recvfrom(2048)
    finally:
        s.close()
    rid, flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", data[:12])
    if rid != tid or flags & 0x000F:
        return []
    off = 12
    for _ in range(qd):  # pomiń pytanie
        while data[off] != 0:
            off += 1 + data[off]
        off += 5
    ips = []
    for _ in range(an):
        if data[off] & 0xC0 == 0xC0:
            off += 2
        else:
            while data[off] != 0:
                off += 1 + data[off]
            off += 1
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10])
        off += 10
        if rtype == 1 and rdlen == 4:
            ips.append(socket.inet_ntoa(data[off:off + 4]))
        off += rdlen
    return ips


def resolve(host):
    """Adresy IP hosta: najpierw systemowy DNS, a gdy zawiedzie – publiczne serwery DNS."""
    errors = []
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        ips = list(dict.fromkeys(i[4][0] for i in infos))
        if ips:
            return ips, "system"
    except OSError as e:
        errors.append(f"systemowy DNS: {e}")
    for server in PUBLIC_DNS:
        try:
            ips = _dns_query(host, server)
            if ips:
                return ips, server
        except OSError as e:
            errors.append(f"{server}: {e}")
    raise NetError("Nie można odnaleźć serwera aktualizacji (DNS nie odpowiada)", "; ".join(errors)[:300])


# --------------------------------------------------------------------------- połączenie

def _proxy_for(host):
    try:
        proxies = urllib.request.getproxies()
        if urllib.request.proxy_bypass(host):
            return None
    except Exception:
        return None
    p = proxies.get("https") or proxies.get("http")
    if not p:
        return None
    u = urllib.parse.urlparse(p if "://" in p else "http://" + p)
    return u.hostname, u.port or 8080


class _Conn(http.client.HTTPSConnection):
    """HTTPS do konkretnego adresu IP (z własnego DNS), z poprawną nazwą serwera dla certyfikatu."""

    def __init__(self, host, ip, timeout, context):
        super().__init__(host, 443, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _friendly(e):
    s = str(e)
    if isinstance(e, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in s:
        return NetError("Windows nie ufa certyfikatowi serwera aktualizacji", s[:200])
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in s:
        return NetError("Serwer aktualizacji nie odpowiada (przekroczony czas)", s[:200])
    if isinstance(e, ConnectionRefusedError):
        return NetError("Połączenie z serwerem aktualizacji zostało odrzucone (zapora/antywirus?)", s[:200])
    if isinstance(e, NetError):
        return e
    return NetError("Błąd połączenia z serwerem aktualizacji", f"{e.__class__.__name__}: {s[:200]}")


def _open_once(url, timeout, ctx):
    u = urllib.parse.urlparse(url)
    host = u.hostname
    path = (u.path or "/") + (("?" + u.query) if u.query else "")
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json, */*", "Host": host}
    proxy = _proxy_for(host)
    if proxy:
        conn = http.client.HTTPSConnection(proxy[0], proxy[1], timeout=timeout, context=ctx)
        conn.set_tunnel(host, 443)
        conn.request("GET", path, headers=headers)
        return conn, conn.getresponse()
    ips, _src = resolve(host)
    last = None
    for ip in ips[:4]:
        conn = _Conn(host, ip, timeout, ctx)
        try:
            conn.request("GET", path, headers=headers)
            return conn, conn.getresponse()
        except ssl.SSLError:
            conn.close()
            raise
        except OSError as e:
            conn.close()
            last = e
    raise last or NetError("Brak połączenia z serwerem aktualizacji")


def open_url(url, timeout=25):
    """Zwraca odpowiedź HTTP (status 200) – z obsługą przekierowań. Wywołujący zamyka .close()."""
    contexts = [ssl_context(), _certifi_context()]  # gdy systemowa weryfikacja zawiedzie – pakiet certifi
    last = None
    for ctx in contexts:
        try:
            for _ in range(6):
                conn, resp = _open_once(url, timeout, ctx)
                if resp.status in (301, 302, 303, 307, 308):
                    url = urllib.parse.urljoin(url, resp.getheader("Location"))
                    resp.read()
                    conn.close()
                    continue
                if resp.status != 200:
                    body = resp.read(300)
                    conn.close()
                    if resp.status == 404:
                        raise NetError("Nie znaleziono wydania na serwerze aktualizacji (404)", body.decode("utf-8", "replace"))
                    if resp.status in (403, 429):
                        raise NetError("Serwer aktualizacji chwilowo ogranicza zapytania – spróbuj za kilka minut",
                                       f"HTTP {resp.status}")
                    raise NetError(f"Serwer aktualizacji zwrócił błąd HTTP {resp.status}", body.decode("utf-8", "replace"))
                resp._pd_conn = conn
                return resp
            raise NetError("Za dużo przekierowań")
        except NetError:
            raise
        except ssl.SSLCertVerificationError as e:  # spróbuj drugim zestawem certyfikatów
            last = e
            continue
        except Exception as e:
            raise _friendly(e)
    raise _friendly(last)


def get_bytes(url, timeout=25):
    r = open_url(url, timeout)
    try:
        return r.read()
    finally:
        r._pd_conn.close()


def get_json(url, timeout=25):
    return json.loads(get_bytes(url, timeout).decode("utf-8"))


def diagnose(host="api.github.com"):
    """Krótki raport dla użytkownika: DNS, połączenie, certyfikat."""
    lines = []
    try:
        ips, src = resolve(host)
        lines.append(f"DNS: OK ({host} -> {ips[0]}, przez {src})")
    except NetError as e:
        lines.append(f"DNS: BŁĄD – {e.detail}")
        return "\n".join(lines)
    p = _proxy_for(host)
    lines.append(f"Proxy: {p[0]}:{p[1]}" if p else "Proxy: brak")
    try:
        s = socket.create_connection((ips[0], 443), 8)
        lines.append("Połączenie TCP 443: OK")
        try:
            ssl_context().wrap_socket(s, server_hostname=host).close()
            lines.append("Certyfikat: OK")
        except Exception as e:
            lines.append(f"Certyfikat: BŁĄD – {str(e)[:160]}")
    except OSError as e:
        lines.append(f"Połączenie TCP 443: BŁĄD – {e}")
    return "\n".join(lines)
