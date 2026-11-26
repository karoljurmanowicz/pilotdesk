"""Test zwykłego trybu (okno programu) na prawdziwym Windows: udostępnianie bez hasła z „Akceptuj/Odrzuć”.

Odtwarza sytuację użytkownika: świeża instalacja, włączony „Zdalny dostęp”, brak hasła, drugi komputer łączy się
po ID. Akceptację klika automatycznie zmienna PILOTDESK_TEST_AUTOACCEPT. Sprawdza też, że drugie uruchomienie
programu nie zamyka działającej kopii, oraz że okno się nie zawiesza.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pd_common import (M_FRAME, M_JSON, M_VIDEO, ensure_host_identity, get_local_ips, save_config,  # noqa: E402
                       viewer_handshake)

SRC = os.path.abspath(os.path.join("dist", "PilotDesk.exe"))
DST_DIR = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "PilotDesk")
EXE = os.path.join(DST_DIR, "PilotDesk.exe")
LOG = os.path.join(os.environ["LOCALAPPDATA"], "PilotDesk", "pilotdesk.log")
results = {}


def section(t):
    print(f"\n===================== {t}", flush=True)


def wait_port(port, secs):
    for i in range(secs):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return i
        except OSError:
            time.sleep(1)
    return None


def ask_session(ip, port):
    t0 = time.time()
    s = socket.create_connection((ip, port), timeout=10)
    s.settimeout(30)
    codes = []
    ch, hello, ok, _ = viewer_handshake(s, None, {"client": "ci@PC1", "video": True}, mode="ask",
                                        on_code=codes.append)
    info = {"auth": True, "code_shown": bool(codes), "name": ok.get("name")}
    got_frame = False
    end = time.time() + 20
    while time.time() < end and not got_frame:
        t, body = ch.recv()
        if t in (M_FRAME, M_VIDEO):
            got_frame = True
        elif t == M_JSON and json.loads(body).get("t") == "monitors":
            info["monitors"] = True
    info["frame"] = got_frame
    for down in (True, False):
        ch.send_json({"t": "mouse_btn", "b": "left", "down": down, "x": 0.4, "y": 0.4})
    time.sleep(1)
    ch.close()
    info["seconds"] = round(time.time() - t0, 1)
    return info


def main():
    os.makedirs(DST_DIR, exist_ok=True)
    shutil.copy2(SRC, EXE)
    cfgp = os.path.join(os.path.expanduser("~"), ".pilotdesk.json")
    cfg = {}
    ensure_host_identity(cfg)
    cfg.update({"host_enabled": True, "ask_enabled": True, "auto_update": False})
    save_config(cfg, cfgp)
    env = dict(os.environ, PILOTDESK_TEST_AUTOACCEPT="1")

    section("start programu (okno)")
    app = subprocess.Popen([EXE], env=env)
    t = wait_port(47800, 90)
    results["port_open_after_s"] = t
    print("port 47800 otwarty po", t, "s")
    if t is None:
        return finish(app, False)
    time.sleep(3)

    section("drugie uruchomienie (ma tylko pokazać okno)")
    t0 = time.time()
    r = subprocess.run([EXE], env=env, timeout=60)
    results["second_launch"] = {"exit": r.returncode, "seconds": round(time.time() - t0, 1),
                                "first_alive": app.poll() is None}
    print(results["second_launch"])

    section("sprawdzenie połączenia (pd_diag)")
    import pd_diag
    ips = [ip for ip in get_local_ips() if not ip.startswith("127.")]
    print(pd_diag.format_lines(pd_diag.check_target(cfg["host_id"], extra_ips=ips)))

    for ip in ips[:1] + ["127.0.0.1"]:
        section(f"połączenie bez hasła (Akceptuj) przez {ip}")
        try:
            info = ask_session(ip, 47800)
        except Exception as e:
            info = {"error": f"{type(e).__name__}: {e}"}
        print(json.dumps(info, ensure_ascii=False))
        results[f"ask_{ip}"] = info
        time.sleep(2)
    ok = all(v.get("auth") and v.get("frame") for k, v in results.items() if k.startswith("ask_"))
    ok = ok and results["second_launch"]["first_alive"]
    return finish(app, ok)


def finish(app, ok):
    section("dziennik programu")
    try:
        text = open(LOG, encoding="utf-8", errors="replace").read()
        print(text[-8000:])
        hung = "Okno nie odpowiada" in text
    except OSError as e:
        print(e)
        hung = False
    results["ui_hang_detected"] = hung
    err = os.path.join(os.environ["LOCALAPPDATA"], "PilotDesk", "error.log")
    if os.path.exists(err):
        print("--- error.log\n" + open(err, encoding="utf-8", errors="replace").read()[-3000:])
    app.kill()
    section("WYNIK")
    print(json.dumps(results, ensure_ascii=False, indent=1))
    ok = ok and not hung
    print("OK" if ok else "BŁĄD")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
