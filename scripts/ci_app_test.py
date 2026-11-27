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


def wait_for(cond, secs):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def clipboard_test(ip, port, password=None):
    """Wspólny schowek na prawdziwym Windows: tekst i pliki w obie strony (ten proces = „drugi komputer”)."""
    import secrets
    import tempfile
    import threading
    import pyperclip
    import pd_clipfiles as CF
    from pd_common import M_FILE, send_file
    s = socket.create_connection((ip, port), timeout=10)
    s.settimeout(60)
    from pd_common import derive_password_key
    kp = (lambda salt: derive_password_key(password, salt)) if password else None
    ch, _hello, _ok, _ = viewer_handshake(s, kp, {"client": "ci-schowek", "video": False,
                                                  "caps": {"clipfiles": True}},
                                          mode="password" if password else "ask")
    msgs = []

    def reader():
        try:
            while True:
                t, body = ch.recv()
                if t == M_JSON:
                    msgs.append(json.loads(body))
                elif t == M_FILE:
                    pass
        except Exception:
            pass
    threading.Thread(target=reader, daemon=True).start()
    time.sleep(2)
    res = {}
    t1 = "PD-z-PC1-zażółć"
    ch.send_json({"t": "clipboard", "text": t1})
    res["tekst_do_komputera_zdalnego"] = wait_for(lambda: pyperclip.paste() == t1, 6)
    t2 = "PD-z-PC2-gęślą-jaźń"
    pyperclip.copy(t2)
    res["tekst_z_komputera_zdalnego"] = wait_for(
        lambda: any(m.get("t") == "clipboard" and m.get("text") == t2 for m in msgs), 8)
    tmp = tempfile.mkdtemp()
    name = "plik-testowy.txt"
    fp = os.path.join(tmp, name)
    with open(fp, "w", encoding="utf-8") as f:
        f.write("PilotDesk " * 1000)
    cid = secrets.token_hex(8)
    ch.send_json({"t": "clip_files_begin", "id": cid, "names": [name], "total": os.path.getsize(fp)})
    send_file(ch, fp, name, extra={"clip": cid})
    ch.send_json({"t": "clip_files_end", "id": cid, "names": [name]})

    def files_on_clip():
        got = CF.get_files() or []
        return any(g.endswith(name) for g in got)
    res["pliki_do_komputera_zdalnego"] = wait_for(files_on_clip, 8)
    fp2 = os.path.join(tmp, "z-drugiej-strony.txt")
    with open(fp2, "w", encoding="utf-8") as f:
        f.write("x" * 5000)
    res["set_files_ok"] = CF.set_files([fp2])
    res["pliki_z_komputera_zdalnego"] = wait_for(
        lambda: any(m.get("t") == "clip_files_end" and "z-drugiej-strony.txt" in m.get("names", []) for m in msgs), 10)
    ch.close()
    return res


def main():
    os.makedirs(DST_DIR, exist_ok=True)
    for _ in range(20):  # poprzedni test mógł jeszcze zamykać program
        try:
            shutil.copy2(SRC, EXE)
            break
        except PermissionError:
            subprocess.run(["taskkill", "/F", "/IM", "PilotDesk.exe"], capture_output=True)
            time.sleep(1)
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
    section("wspólny schowek (Ctrl+C / Ctrl+V)")
    try:
        results["schowek"] = clipboard_test("127.0.0.1", 47800)
    except Exception as e:
        import traceback
        results["schowek"] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
    print(json.dumps(results["schowek"], ensure_ascii=False, indent=1))
    ok = all(v.get("auth") and v.get("frame") for k, v in results.items() if k.startswith("ask_"))
    ok = ok and all(v is True for k, v in results["schowek"].items())
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
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(app.pid)], capture_output=True)
    section("WYNIK")
    print(json.dumps(results, ensure_ascii=False, indent=1))
    ok = ok and not hung
    print("OK" if ok else "BŁĄD")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
