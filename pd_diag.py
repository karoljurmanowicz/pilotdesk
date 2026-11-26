"""PilotDesk – diagnostyka: sprawdzanie połączenia z innym komputerem krok po kroku i raport do wysłania.

Wszystko po polsku i bez żargonu – czyta to użytkownik, nie programista.
"""
import json
import os
import platform
import socket
import subprocess
import sys
import time

# wyjście poleceń Windows (sc, netsh, netstat) jest w kodowaniu konsoli – polskie znaki psuły odczyt
CON_ENC = "oem" if sys.platform == "win32" else None
import zipfile

from pd_common import (APP_NAME, DEFAULT_PORT, PROTO, VERSION, format_id, get_local_ips, hostname, parse_target,
                       recv_plain)

OK, BAD, INFO = "✓", "✗", "•"
SECRET_KEYS = {"pw_key", "pw_salt", "id_secret", "key", "salt", "relay_key", "device_key", "control_token", "pub",
               "pw"}
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _probe_hello(ip, port, timeout=6):
    """Łączy się i czyta powitanie komputera zdalnego (bez logowania). Zwraca (wynik, opis)."""
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
    except ConnectionRefusedError:
        return BAD, f"{ip}:{port} – odmowa połączenia (na tym porcie nic nie nasłuchuje)"
    except (socket.timeout, TimeoutError):
        return BAD, f"{ip}:{port} – brak odpowiedzi (najczęściej blokuje zapora Windows na tamtym komputerze)"
    except OSError as e:
        return BAD, f"{ip}:{port} – {e.strerror or e}"
    try:
        s.settimeout(timeout)
        hello = recv_plain(s)
    except ConnectionError:
        return BAD, (f"{ip}:{port} – połączenie przyjęte, ale tamten komputer od razu je zamknął "
                     "(zobacz dziennik zdarzeń na tamtym komputerze)")
    except (socket.timeout, TimeoutError):
        return BAD, f"{ip}:{port} – połączenie przyjęte, ale brak powitania (program po drugiej stronie nie odpowiada)"
    except Exception as e:
        return BAD, f"{ip}:{port} – nieoczekiwana odpowiedź: {e}"
    finally:
        try:
            s.close()
        except OSError:
            pass
    if hello.get("error"):
        return BAD, f"{ip}:{port} – PilotDesk odmawia: {hello['error']}"
    if hello.get("app") != APP_NAME:
        return BAD, f"{ip}:{port} – na tym porcie działa inny program niż PilotDesk"
    if hello.get("proto") != PROTO:
        return BAD, f"{ip}:{port} – inna wersja protokołu – zaktualizuj PilotDesk na obu komputerach"
    modes = []
    if hello.get("pw"):
        modes.append("z hasłem")
    if hello.get("ask"):
        modes.append("bez hasła po akceptacji")
    if not modes:
        return BAD, f"{ip}:{port} – PilotDesk działa, ale nie przyjmuje żadnych połączeń (brak hasła i akceptacji)"
    return OK, f"{ip}:{port} – PilotDesk „{hello.get('name', '?')}” odpowiada; przyjmuje połączenia: {', '.join(modes)}"


def check_target(target, extra_ips=(), my_id=None, relay=""):
    """Sprawdza krok po kroku, czy da się połączyć z `target` (ID albo adres). Zwraca listę (znak, tekst)."""
    import pd_discovery
    out = []
    kind = parse_target(target)
    ips, port = [], DEFAULT_PORT
    if kind[0] == "id":
        hid = kind[1]
        out.append((INFO, f"Szukam komputera o ID {format_id(hid)} w sieci lokalnej i Tailscale…"))
        try:
            found = pd_discovery.discover(want_id=hid, timeout=2.5, extra=[i for i in extra_ips if i],
                                          exclude_id=my_id).get(hid)
        except Exception as e:
            found = None
            out.append((BAD, f"Wyszukiwanie nie działa: {e}"))
        if not found:
            out.append((BAD, "Nie znaleziono. Na tamtym komputerze sprawdź, czy PilotDesk jest uruchomiony i ma "
                             "włączony „Zdalny dostęp”, i czy oba komputery są w tej samej sieci (albo w Tailscale)."))
            if relay:
                out.append((INFO, f"Ustawiony jest serwer pośredniczący {relay} – połączenie spróbuje przez niego."))
            return out
        ips = found.get("ips") or [found["ip"]]
        port = int(found.get("port") or 0)
        out.append((OK, f"Znaleziono: {found.get('name') or '?'} ({found.get('os', '')}), adresy: {', '.join(ips)}, "
                        f"port {port or 'BRAK'}"))
        if not port:
            out.append((BAD, "Tamten komputer nie nasłuchuje na żadnym porcie TCP – uruchom go ponownie i sprawdź "
                             "Dostęp → dziennik."))
            return out
    else:
        ips, port = [kind[1]], kind[2]
    good = False
    for ip in ips:
        mark, text = _probe_hello(ip, port)
        out.append((mark, text))
        good = good or mark == OK
        if good:
            break
    if good:
        out.append((OK, "Połączenie jest możliwe. Jeśli łączenie nadal się nie udaje, sprawdź hasło albo kliknij "
                        "„Akceptuj” na tamtym komputerze."))
    elif kind[0] == "id":
        out.append((INFO, "Gdy zapora blokuje połączenia, PilotDesk próbuje też połączenia zwrotnego. Najprościej: "
                          "na tamtym komputerze PilotDesk → Dostęp → „Napraw zaporę”."))
    return out


def format_lines(lines):
    return "\n".join(f"{m}  {t}" for m, t in lines)


# --------------------------------------------------------------------------- raport

def _redact(obj):
    if isinstance(obj, dict):
        return {k: ("***" if k in SECRET_KEYS and v else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _cmd(args, timeout=15):
    try:
        r = subprocess.run(args, capture_output=True, encoding=CON_ENC, errors="replace", timeout=timeout,
                           creationflags=NO_WINDOW)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"(nie udało się: {e})"


def system_summary(cfg, hcfg, host=None):
    lines = [f"PilotDesk {VERSION} · {hostname()} · {platform.platform()} · Python {sys.version.split()[0]}",
             f"Czas: {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"Adresy: {', '.join(get_local_ips())}",
             f"ID: {format_id(hcfg.get('host_id', ''))}"]
    if host is not None:
        lines.append(f"Udostępnianie: {type(host).__name__}, bezpośrednio: {getattr(host, 'direct_status', '?')}, "
                     f"serwer: {getattr(host, 'relay_status', '?')}, sesje: {len(getattr(host, 'sessions', []))}, "
                     f"usługa odpowiada: {getattr(host, 'connected', '-')}")
    else:
        lines.append("Udostępnianie: wyłączone")
    if sys.platform == "win32":
        lines.append("\n--- Porty PilotDesk (netstat)")
        lines += [ln for ln in _cmd(["netstat", "-ano"]).splitlines() if ":478" in ln][:30]
        lines.append("\n--- Usługa")
        lines.append(_cmd(["sc", "query", "PilotDeskService"]))
        lines.append("\n--- Reguły zapory PilotDesk")
        fw = _cmd(["netsh", "advfirewall", "firewall", "show", "rule", "name=all", "verbose"], timeout=30)
        block, keep = [], False
        for ln in fw.splitlines():
            if ln.startswith("Rule Name:") or ln.startswith("Nazwa reguły:"):
                keep = "pilotdesk" in ln.lower()
            if keep or "pilotdesk" in ln.lower():
                block.append(ln)
        lines += block[:200] or ["(brak reguł z nazwą PilotDesk)"]
        lines.append("\n--- Profil sieci")
        lines.append(_cmd(["netsh", "advfirewall", "show", "currentprofile"]))
    lines.append("\n--- Ustawienia (bez haseł i kluczy)")
    lines.append(json.dumps(_redact(cfg), ensure_ascii=False, indent=1))
    if hcfg is not cfg:
        lines.append("\n--- Ustawienia usługi (bez haseł i kluczy)")
        lines.append(json.dumps(_redact(hcfg), ensure_ascii=False, indent=1))
    return "\n".join(lines)


def _log_files():
    import pd_log
    out = []
    dirs = [pd_log.log_dir()]
    if sys.platform == "win32":
        dirs.append(os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "PilotDesk", "logs"))
        dirs.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "PilotDesk"))
    for d in dict.fromkeys(dirs):
        try:
            for f in sorted(os.listdir(d)):
                if f.endswith(".log") or ".log." in f:
                    out.append(os.path.join(d, f))
        except OSError:
            pass
    return out


def make_report(cfg, hcfg, host=None, dest_dir=None):
    """Tworzy PilotDesk-raport-*.zip (dzienniki + opis systemu, bez haseł). Zwraca ścieżkę."""
    if dest_dir is None:
        dest_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(dest_dir):
            dest_dir = os.path.expanduser("~")
    name = f"PilotDesk-raport-{hostname()}-{time.strftime('%Y%m%d-%H%M')}.zip"
    path = os.path.join(dest_dir, name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("system.txt", system_summary(cfg, hcfg, host))
        for i, f in enumerate(_log_files()):
            try:
                z.write(f, f"logi/{i:02d}-{os.path.basename(os.path.dirname(f))}-{os.path.basename(f)}")
            except OSError:
                pass
    return path
