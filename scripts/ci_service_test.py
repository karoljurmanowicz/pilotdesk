"""Test usługi systemowej na prawdziwym Windows (GitHub Actions, konto administratora).

Instaluje usługę z dist/PilotDesk.exe, czeka na agenta, łączy się jak zwykły klient (hasło), sprawdza obraz,
kliknięcie i wyszukiwanie po ID, wypisuje dzienniki i odinstalowuje usługę. Kod wyjścia != 0 = błąd.
"""
import glob
import json
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pd_common import (M_FRAME, M_JSON, M_VIDEO, derive_password_key, ensure_host_identity, get_local_ips,  # noqa: E402
                       open_tcp, save_config, set_host_password, viewer_handshake)

EXE = os.path.abspath(os.path.join("dist", "PilotDesk.exe"))
PW = "test1234"
results = {}


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors="replace")
    return (r.stdout + r.stderr).strip()


def section(title):
    print(f"\n===================== {title}", flush=True)


def try_session(addr, port):
    t0 = time.time()
    sock = open_tcp(addr, port, timeout=10)
    ch, hello, ok, _ = viewer_handshake(sock, lambda salt: derive_password_key(PW, salt),
                                        {"name": "ci-test", "video": True})
    info = {"auth": True, "host": ok.get("name"), "service": hello.get("service") or ok.get("service")}
    sock.settimeout(15)
    got_mon = got_frame = False
    end = time.time() + 20
    while time.time() < end and not (got_mon and got_frame):
        t, body = ch.recv()
        if t == M_JSON:
            m = json.loads(body)
            if m.get("t") == "monitors":
                got_mon = True
                info["monitors"] = m.get("list")
        elif t in (M_FRAME, M_VIDEO):
            got_frame = True
            ch.send_json({"t": "ack"})
    info["monitors_msg"] = got_mon
    info["frame"] = got_frame
    for down in (True, False):
        ch.send_json({"t": "mouse_btn", "b": "left", "down": down, "x": 0.5, "y": 0.5})
    time.sleep(1)
    ch.close()
    info["seconds"] = round(time.time() - t0, 1)
    return info


def main():
    cfgp = os.path.abspath("ci_user_cfg.json")
    cfg = {}
    ensure_host_identity(cfg)
    set_host_password(cfg, PW)
    cfg["ask_enabled"] = False
    save_config(cfg, cfgp)

    section("instalacja usługi")
    r = subprocess.run([EXE, "--install-service", cfgp], timeout=180)
    results["install_rc"] = r.returncode
    print("kod:", r.returncode)

    section("czekam na agenta (port 47800)")
    port_ok = False
    for i in range(90):
        try:
            socket.create_connection(("127.0.0.1", 47800), timeout=1).close()
            port_ok = True
            print(f"port otwarty po ~{i * 2} s")
            break
        except OSError:
            time.sleep(2)
    results["port_open"] = port_ok
    print(sh("sc query PilotDeskService"))
    print(sh('tasklist /v /fo csv | findstr /i pilotdesk'))
    print(sh("netstat -ano | findstr 478"))
    print(sh('netsh advfirewall firewall show rule name="PilotDesk Service"'))

    if port_ok:
        time.sleep(3)
        for addr in ["127.0.0.1"] + [ip for ip in get_local_ips() if not ip.startswith("127.")][:2]:
            section(f"sesja przez {addr}")
            try:
                info = try_session(addr, 47800)
            except Exception as e:
                info = {"error": f"{type(e).__name__}: {e}"}
            print(json.dumps(info, ensure_ascii=False, indent=1))
            results[f"session_{addr}"] = info
        section("wyszukiwanie po ID")
        try:
            import pd_discovery
            ips = [ip for ip in get_local_ips() if not ip.startswith("127.")]
            found = pd_discovery.discover(want_id=cfg["host_id"], timeout=3, extra=ips + ["127.0.0.1"])
            results["discovery"] = bool(found.get(cfg["host_id"]))
            print(found)
        except Exception as e:
            results["discovery"] = f"błąd: {e}"
            print(results["discovery"])

    section("dzienniki usługi")
    pd = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    for f in glob.glob(os.path.join(pd, "PilotDesk", "logs", "*")) + glob.glob(
            r"C:\Windows\System32\config\systemprofile\AppData\Local\PilotDesk\*.log"):
        print(f"--- {f}")
        try:
            print(open(f, encoding="utf-8", errors="replace").read()[-6000:])
        except OSError as e:
            print(e)
    print(sh('powershell -NoProfile -Command "Get-EventLog -LogName Application -Newest 60 | '
             'Where-Object { $_.Source -like \'*PilotDesk*\' } | Format-List TimeGenerated,EntryType,Source,Message"'))
    print(sh('powershell -NoProfile -Command "Get-EventLog -LogName System -Newest 20 -Source \'Service Control Manager\' | '
             'Where-Object { $_.Message -like \'*PilotDesk*\' } | Format-List TimeGenerated,EntryType,Message"'))

    section("odinstalowanie")
    r = subprocess.run([EXE, "--uninstall-service"], timeout=120)
    print("kod:", r.returncode, "|", sh("sc query PilotDeskService"))

    section("WYNIK")
    print(json.dumps(results, ensure_ascii=False, indent=1))
    s = results.get("session_127.0.0.1") or {}
    ok = results.get("install_rc") == 0 and port_ok and s.get("auth") and s.get("frame")
    print("OK" if ok else "BŁĄD")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
