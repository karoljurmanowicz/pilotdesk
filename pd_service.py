"""PilotDesk – usługa Windows (dostęp do ekranu logowania i okien UAC, praca po restarcie bez logowania).

Jak to działa:
  * usługa „PilotDeskService” działa jako SYSTEM w sesji 0 (bez ekranu),
  * w aktywnej sesji konsoli uruchamia AGENTA (`PilotDesk.exe --agent`) z tokenem SYSTEM – tylko taki
    proces może przełączać się na pulpit Winlogon (ekran logowania, Ctrl+Alt+Del, okna UAC),
  * agent przyjmuje połączenia (jak zwykły tryb udostępniania) i przed każdym zrzutem ekranu oraz
    zdarzeniem myszy/klawiatury przełącza się na pulpit, który akurat jest aktywny,
  * okno PilotDesk zalogowanego użytkownika łączy się z agentem przez 127.0.0.1 (lista sesji, czat,
    pytania „Akceptuj/Odrzuć”, rozłączanie),
  * usługa sama sprawdza i instaluje aktualizacje.
"""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time

# wyjście poleceń Windows (sc, netsh, netstat) jest w kodowaniu konsoli – polskie znaki psuły odczyt
CON_ENC = "oem" if sys.platform == "win32" else None

from pd_common import (VERSION, load_config, machine_config_path, machine_dir, save_config, update_source)

SERVICE_NAME = "PilotDeskService"


def _log(msg):
    try:
        import pd_log
        pd_log.info("%s", msg)
    except Exception:
        pass


CONTROL_PORT = 47803
NO_WINDOW = 0x08000000
DETACHED = 0x00000008
BREAKAWAY = 0x01000000
HOST_KEYS = ("host_id", "id_secret", "pw_salt", "pw_key", "relay", "relay_key", "listen_port", "direct_enabled",
             "ask_enabled", "update_source", "auto_update", "trusted")
FW_RULE = "PilotDesk Service"  # ASCII – netsh/cmd psują polskie znaki


def program_dir():
    return os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "PilotDesk")


def program_exe():
    return os.path.join(program_dir(), "PilotDesk.exe")


def _sc(*args, check=False):
    r = subprocess.run(["sc", *args], capture_output=True, encoding=CON_ENC, errors="replace", creationflags=NO_WINDOW)
    if check and r.returncode != 0:
        raise OSError((r.stdout + r.stderr).strip()[-300:])
    return r


def service_installed():
    if sys.platform != "win32":
        return False
    return _sc("query", SERVICE_NAME).returncode == 0


def service_running():
    return sys.platform == "win32" and "RUNNING" in _sc("query", SERVICE_NAME).stdout


def _netsh(*args):
    return subprocess.run(["netsh", "advfirewall", "firewall", *args], capture_output=True, encoding=CON_ENC, errors="replace",
                          creationflags=NO_WINDOW)


def set_firewall_rules(on=True):
    """Usługa działa z kopii programu w Program Files – reguła zapory dla zwykłego PilotDesk.exe jej nie obejmuje,
    a Windows nie pyta o zgodę dla procesów SYSTEM. Bez tej reguły nikt nie mógł się połączyć."""
    _netsh("delete", "rule", f"name={FW_RULE}")
    if not on:
        return True
    r1 = _netsh("add", "rule", f"name={FW_RULE}", "dir=in", "action=allow", f"program={program_exe()}",
                "enable=yes", "profile=any")
    r2 = _netsh("add", "rule", f"name={FW_RULE}", "dir=in", "action=allow", "protocol=UDP", "localport=47802",
                "enable=yes", "profile=any")
    return r1.returncode == 0 and r2.returncode == 0


def kill_stray_agents(exclude_pid=None):
    """Zamyka wszystkie procesy agenta (PilotDesk.exe --agent), także „osierocone”.

    PilotDesk.exe (PyInstaller onefile) to dwa procesy: opakowanie i właściwy program. Usługa zamykała tylko
    opakowanie, a właściwy agent działał dalej – ze starą wersją, trzymając porty 47800/47802/47803. Po podmianie
    pliku programu taki agent nie mógł już doczytać swoich modułów („Error -3 while decompressing data”) i odrzucał
    każde połączenie („Połączenie zostało zamknięte”)."""
    if sys.platform != "win32":
        return 0
    ex = f" -and $_.ProcessId -ne {int(exclude_pid)}" if exclude_pid else ""
    script = ("$n=0; Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'PilotDesk*.exe' -and "
              f"$_.CommandLine -like '*--agent*'{ex} }} | ForEach-Object {{ "
              "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }; $n")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, encoding=CON_ENC, errors="replace", timeout=60,
                           creationflags=NO_WINDOW)
        n = int((r.stdout or "0").strip().splitlines()[-1] or 0)
    except Exception as e:
        _log(f"Nie udało się zamknąć starych agentów: {e!r}")
        return 0
    if n:
        _log(f"Zamknięto stare procesy agenta: {n}")
    return n


def _kill_tree(pid):
    if not pid:
        return
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(int(pid))], capture_output=True, creationflags=NO_WINDOW)


def _wait_state(state, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        out = _sc("query", SERVICE_NAME).stdout
        if state in out or (state == "STOPPED" and _sc("query", SERVICE_NAME).returncode != 0):
            return True
        time.sleep(0.5)
    return False


# --------------------------------------------------------------------------- instalacja (jako administrator)

def install_service(user_config_path):
    """Wywoływane w procesie z uprawnieniami administratora: PilotDesk.exe --install-service <config>."""
    src = sys.executable
    if service_installed():
        _sc("stop", SERVICE_NAME)
        _wait_state("STOPPED")
    kill_stray_agents()  # inaczej stary agent działa dalej z podmienionego pliku
    os.makedirs(program_dir(), exist_ok=True)
    if os.path.abspath(src).lower() != program_exe().lower():
        for _ in range(20):
            try:
                if os.path.exists(program_exe()):
                    os.replace(program_exe(), program_exe() + ".old")
                shutil.copy2(src, program_exe())
                break
            except OSError:
                time.sleep(0.5)
    os.makedirs(machine_dir(), exist_ok=True)
    ucfg = load_config(user_config_path) if user_config_path else {}
    mcfg = load_config(machine_config_path())
    for k in HOST_KEYS:
        if k in ucfg:
            mcfg[k] = ucfg[k]
    mcfg.setdefault("control_token", secrets.token_hex(24))
    save_config(mcfg, machine_config_path())
    # użytkownicy mogą zmieniać ustawienia udostępniania z okna programu (hasło, serwer)
    subprocess.run(["icacls", machine_dir(), "/grant", "*S-1-5-32-545:(OI)(CI)M", "/T", "/Q"],
                   capture_output=True, creationflags=NO_WINDOW)
    try:
        _log("Zapora: reguła dla usługi " + ("dodana" if set_firewall_rules(True) else "NIE została dodana"))
    except Exception as e:
        _log(f"Zapora: błąd {e}")
    bin_path = f'"{program_exe()}" --service'
    if service_installed():
        _sc("config", SERVICE_NAME, "binPath=", bin_path, "start=", "auto", check=True)
    else:
        _sc("create", SERVICE_NAME, "binPath=", bin_path, "start=", "auto", "DisplayName=", "PilotDesk", check=True)
    _sc("description", SERVICE_NAME, "PilotDesk - zdalny dostęp do tego komputera (także ekran logowania i UAC).")
    _sc("failure", SERVICE_NAME, "reset=", "86400", "actions=", "restart/5000/restart/5000/restart/30000")
    _sc("start", SERVICE_NAME)
    return 0


def uninstall_service():
    _sc("stop", SERVICE_NAME)
    _wait_state("STOPPED")
    _sc("delete", SERVICE_NAME)
    kill_stray_agents()
    try:
        set_firewall_rules(False)
    except Exception:
        pass
    try:
        os.remove(machine_config_path())
    except OSError:
        pass
    for p in (program_exe(), program_exe() + ".old"):
        for _ in range(10):
            try:
                if os.path.exists(p):
                    os.remove(p)
                break
            except OSError:
                time.sleep(0.5)
    return 0


def service_self_update():
    """Uruchamiane jako `PilotDesk.new.exe --service-update` przez usługę: podmienia program i restartuje usługę."""
    _sc("stop", SERVICE_NAME)
    _wait_state("STOPPED", 60)
    kill_stray_agents()
    time.sleep(1)
    for _ in range(30):
        try:
            if os.path.exists(program_exe()):
                os.replace(program_exe(), program_exe() + ".old")
            shutil.copy2(sys.executable, program_exe())
            break
        except OSError:
            time.sleep(1)
    _sc("start", SERVICE_NAME)
    return 0


_update_lock = threading.Lock()


def service_update_check(force=False):
    """Pobiera nową wersję i podmienia program usługi (proces `--service-update`). Działa w usłudze i w agencie
    (oba jako SYSTEM). force – na prośbę okna, nawet gdy automatyczne aktualizacje są wyłączone."""
    if not _update_lock.acquire(blocking=False):
        return False
    try:
        import pd_update
        cfg = load_config(machine_config_path())
        src = update_source(cfg) or update_source({})
        if not src or not (force or cfg.get("auto_update", True)):
            return False
        info = pd_update.check(src)
        if not info or not pd_update.newer(info["version"], VERSION):
            return False
        _log(f"Aktualizacja usługi {VERSION} → {info['version']}")
        new = pd_update.download(info, os.path.join(program_dir(), "PilotDesk.new.exe"))
        subprocess.Popen([new, "--service-update"], creationflags=NO_WINDOW | DETACHED | BREAKAWAY, close_fds=True)
        return True
    except Exception as e:
        _log(f"Aktualizacja usługi nieudana: {e!r}")
        raise
    finally:
        _update_lock.release()


# --------------------------------------------------------------------------- usługa

def run_service_dispatcher():
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class PilotDeskService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = "PilotDesk"
        _svc_description_ = "PilotDesk - zdalny dostęp"

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_evt = win32event.CreateEvent(None, 0, 0, None)
            self.proc = None
            self.pid = None
            self.sid = None
            self.last_spawn = 0

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_evt)

        def SvcDoRun(self):
            servicemanager.LogInfoMsg("PilotDesk: start usługi")
            try:
                self.main()
            except Exception as e:
                servicemanager.LogErrorMsg(f"PilotDesk: błąd usługi: {e}")
            self._kill()

        def _alive(self):
            import win32process
            try:
                return self.proc is not None and win32process.GetExitCodeProcess(self.proc) == 259
            except Exception:
                return False

        def _kill(self):
            import win32api
            if self.proc is not None:
                _kill_tree(getattr(self, "pid", None))  # całe drzewo: opakowanie onefile + właściwy agent
                try:
                    win32api.TerminateProcess(self.proc, 0)
                except Exception:
                    pass
                self.proc = None
                self.pid = None

        def _spawn(self, sid):
            import win32api
            import win32con
            import win32process
            import win32profile
            import win32security
            tok = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ALL_ACCESS)
            dup = win32security.DuplicateTokenEx(tok, win32security.SecurityImpersonation, win32con.TOKEN_ALL_ACCESS,
                                                 win32security.TokenPrimary)
            win32security.SetTokenInformation(dup, win32security.TokenSessionId, sid)
            si = win32process.STARTUPINFO()
            si.lpDesktop = "winsta0\\default"
            env = win32profile.CreateEnvironmentBlock(dup, False)
            cmd = f'"{sys.executable}" --agent'
            hp, ht, pid, _tid = win32process.CreateProcessAsUser(
                dup, None, cmd, None, None, False, NO_WINDOW | win32con.CREATE_UNICODE_ENVIRONMENT, env, None, si)
            ht.Close()
            self.proc = hp
            self.pid = pid
            self.sid = sid

        def _ensure_firewall(self):
            """Usługi zainstalowane przed 3.7 nie miały reguły zapory – dodajemy ją przy starcie (jesteśmy SYSTEM)."""
            try:
                if _netsh("show", "rule", f"name={FW_RULE}").returncode != 0:
                    _log("Zapora: brak reguły dla usługi – dodaję: " + ("OK" if set_firewall_rules(True) else "BŁĄD"))
            except Exception as e:
                _log(f"Zapora: {e}")

        def main(self):
            import win32ts
            _log(f"Usługa {VERSION} uruchomiona ({sys.executable})")
            kill_stray_agents()  # agenci pozostali po poprzedniej wersji usługi
            threading.Thread(target=self._ensure_firewall, daemon=True).start()
            last_upd = time.time() - 3 * 3600 + 120  # pierwsze sprawdzenie aktualizacji po 2 min, potem co 3 h
            while win32event.WaitForSingleObject(self.stop_evt, 2000) != win32event.WAIT_OBJECT_0:
                sid = win32ts.WTSGetActiveConsoleSessionId()
                if sid != 0xFFFFFFFF and (sid != self.sid or not self._alive()) and time.time() - self.last_spawn > 3:
                    self._kill()
                    self.last_spawn = time.time()
                    try:
                        self._spawn(sid)
                        _log(f"Uruchomiono agenta w sesji {sid}")
                    except Exception as e:
                        _log(f"Nie można uruchomić agenta w sesji {sid}: {e!r}")
                        servicemanager.LogErrorMsg(f"PilotDesk: nie można uruchomić agenta: {e}")
                if time.time() - last_upd > 3 * 3600:
                    last_upd = time.time()
                    threading.Thread(target=self._check_update, daemon=True).start()

        def _check_update(self):
            try:
                service_update_check()
            except Exception as e:
                servicemanager.LogErrorMsg(f"PilotDesk: aktualizacja nieudana: {e}")

    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(PilotDeskService)
    servicemanager.StartServiceCtrlDispatcher()


# --------------------------------------------------------------------------- agent (w sesji użytkownika)

def _shutdown(sock):
    """Przerywa gniazdo, na którym inny wątek czeka w odczycie. Zamykanie obiektu makefile() w takiej sytuacji
    blokowało się (czekało na blokadę trzymaną przez czytający wątek) – tak zawieszało się zamykanie okna."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


class ControlServer:
    """Kanał agent <-> okno programu użytkownika (127.0.0.1, z tokenem)."""

    def __init__(self, token):
        self.token = token
        self.conn = None
        self.wlock = threading.Lock()
        self.svc = None
        self.asks = {}
        self.logs = []

    def start(self):
        for i in range(15):  # poprzedni agent może jeszcze zwalniać port
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", CONTROL_PORT))
                break
            except OSError:
                s.close()
                if i == 14:
                    raise
                time.sleep(1)
        s.listen(4)
        threading.Thread(target=self._accept, args=(s,), daemon=True).start()

    def _accept(self, s):
        while True:
            c, _ = s.accept()
            threading.Thread(target=self._client, args=(c,), daemon=True).start()

    def _client(self, c):
        f = c.makefile("rwb")
        try:
            hello = json.loads(f.readline() or b"{}")
            if hello.get("op") != "hello" or hello.get("token") != self.token:
                c.close()
                return
            old, self.conn = self.conn, f
            old_sock, self.conn_sock = getattr(self, "conn_sock", None), c
            if old is not None and old_sock is not None:
                _shutdown(old_sock)  # nie f.close(): zamknięcie pliku czeka na wątek, który z niego czyta
            self.sessions_changed()
            self.status()
            for line in self.logs[-50:]:
                self.emit({"ev": "log", "text": line})
            for line in f:
                m = json.loads(line)
                op = m.get("op")
                sess = {s.id: s for s in list(self.svc.sessions)} if self.svc else {}
                if op == "kick":
                    for sid, s in sess.items():
                        if not m.get("sid") or m["sid"] == sid:
                            s.stop()
                elif op == "chat" and m.get("sid") in sess:
                    sess[m["sid"]].send_chat(m.get("text", ""))
                elif op == "clip_files":  # pliki skopiowane przez użytkownika (okno widzi schowek, SYSTEM nie)
                    for s in sess.values():
                        if getattr(s, "clip", None):
                            s.clip.external_files(m.get("paths") or [])
                elif op == "update":
                    threading.Thread(target=lambda: _safe(service_update_check, True), daemon=True).start()
                elif op == "answer":
                    a = self.asks.get(m.get("rid"))
                    if a:
                        a[1] = (bool(m.get("ok")), bool(m.get("remember")))
                        a[0].set()
        except Exception:
            pass
        finally:
            if self.conn is f:
                self.conn = None

    def emit(self, obj):
        f = self.conn
        if not f:
            return False
        try:
            with self.wlock:
                f.write((json.dumps(obj) + "\n").encode())
                f.flush()
            return True
        except Exception:
            return False

    # --- wywołania z HostService
    def log(self, text):
        try:
            import pd_log
            pd_log.info("[agent] %s", text)
        except Exception:
            pass
        line = time.strftime("%H:%M:%S  ") + text
        self.logs = (self.logs + [line])[-200:]
        self.emit({"ev": "log", "text": line})

    def status(self):
        if self.svc:
            self.emit({"ev": "status", "direct": self.svc.direct_status, "relay": self.svc.relay_status,
                       "version": VERSION})

    def sessions_changed(self):
        if self.svc:
            self.emit({"ev": "sessions", "list": [{"id": s.id, "client": s.client, "peer": s.peer, "started": s.started}
                                                  for s in list(self.svc.sessions)]})

    def chat(self, sess, text):
        self.emit({"ev": "chat", "sid": sess.id, "client": sess.client, "text": text})

    def ask(self, client, peer, code, dev=None):
        rid = secrets.token_hex(6)
        ev = threading.Event()
        self.asks[rid] = [ev, (False, False)]
        if not self.emit({"ev": "ask", "rid": rid, "client": client, "peer": peer, "code": code, "device": bool(dev)}):
            self.asks.pop(rid, None)
            return False  # nikt nie jest zalogowany przy komputerze – odrzucamy
        ev.wait(60)
        return self.asks.pop(rid, [None, (False, False)])[1]


def _exe_stamp():
    try:
        st = os.stat(sys.executable)
        return (st.st_size, st.st_mtime)
    except OSError:
        return None


def _agent_obsolete(stamp):
    """Agent ze starego pliku programu (podmienionego) albo bez usługi nie może dalej przyjmować połączeń."""
    if not getattr(sys, "frozen", False):
        return False
    from pd_common import service_registered
    return _exe_stamp() != stamp or not service_registered()


def run_agent():
    from pd_host import HostService
    path = machine_config_path()
    cfg = load_config(path)
    _log(f"Agent {VERSION} start (pid {os.getpid()}), konfiguracja {path}: ID={cfg.get('host_id')}, "
         f"hasło={'tak' if cfg.get('pw_key') else 'nie'}, port={cfg.get('listen_port')}")
    ctl = ControlServer(cfg.get("control_token", ""))
    svc = HostService(cfg, log=ctl.log, on_chat=ctl.chat, on_sessions=ctl.sessions_changed, on_status=ctl.status,
                      ask=ctl.ask, agent_mode=True, save_cfg=lambda: save_config(cfg, path))
    ctl.svc = svc
    ctl.start()
    mtime = 0
    exe_stamp = _exe_stamp()
    checks = 0
    while True:
        checks += 1
        if checks % 5 == 0 and _agent_obsolete(exe_stamp):
            ctl.log("Program usługi został zaktualizowany albo usunięty – ten agent kończy pracę")
            svc.stop()
            os._exit(0)
        try:
            m = os.path.getmtime(path)
        except OSError:
            m = 0
        if m != mtime:
            mtime = m
            new = load_config(path)
            cfg.clear()
            cfg.update(new)
            ctl.token = cfg.get("control_token", ctl.token)
            svc.stop(kick=False)
            if not cfg.get("host_id"):  # brak konfiguracji usługi (np. usunięta) – nie udostępniamy z pustą
                ctl.log("Brak konfiguracji usługi – udostępnianie wstrzymane")
                time.sleep(2)
                continue
            try:
                svc.start()
                ctl.log("Agent usługi uruchomiony – dostęp także do ekranu logowania i okien UAC")
            except Exception as e:
                ctl.log(f"Udostępnianie nieaktywne: {e}")
        time.sleep(2)


# --------------------------------------------------------------------------- strona okna programu

class _SessionProxy:
    def __init__(self, client_obj, d):
        self._c = client_obj
        self.id = d["id"]
        self.client = d["client"]
        self.peer = d["peer"]
        self.started = d["started"]

    def stop(self):
        self._c.send({"op": "kick", "sid": self.id})

    def send_chat(self, text):
        self._c.send({"op": "chat", "sid": self.id, "text": text})

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, o):
        return isinstance(o, _SessionProxy) and o.id == self.id


class ServiceHostProxy:
    """Udaje HostService w oknie programu, gdy udostępnianiem zajmuje się usługa."""

    def __init__(self, log, on_chat, on_sessions, on_status, on_ask):
        self.log, self.on_chat, self.on_sessions, self.on_status, self.on_ask = log, on_chat, on_sessions, on_status, on_ask
        self.sessions = set()
        self.direct_status = "usługa – łączenie…"
        self.relay_status = "—"
        self.running = True
        self.f = None
        self.sock = None
        self.wlock = threading.Lock()
        self.caps = {}
        self.started = time.time()
        self.agent_version = None
        self._update_asked = False
        self.connected = False  # czy agent usługi odpowiada (okno pokazuje prawdziwy stan, nie „Gotowy” na ślepo)
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._clip_watch, name="clip-watch", daemon=True).start()

    def start(self):
        pass

    def stop(self, kick=False):
        self.running = False
        if self.sock is not None:
            _shutdown(self.sock)

    def disconnect_all(self):
        self.send({"op": "kick"})

    def send(self, obj):
        if self.f:
            try:
                with self.wlock:
                    self.f.write((json.dumps(obj) + "\n").encode())
                    self.f.flush()
            except Exception:
                pass

    def _loop(self):
        while self.running:
            try:
                token = load_config(machine_config_path()).get("control_token", "")
                s = socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=5)
                s.settimeout(None)
                self.sock = s
                if not self.running:
                    _shutdown(s)
                    break
                self.f = s.makefile("rwb")
                self.send({"op": "hello", "token": token})
                for line in self.f:
                    self._event(json.loads(line))
            except Exception:
                pass
            self.f = None
            self.connected = False
            if self.sessions:
                self.sessions = set()
                self.on_sessions()
            self.direct_status = "usługa nie odpowiada – ponawiam"
            self.on_status()
            time.sleep(3)

    def _clip_watch(self):
        """Tryb usługi: Windows nie pokazuje agentowi (SYSTEM) plików ze schowka użytkownika – okno programu
        sprawdza schowek i przekazuje listę plików agentowi, a ten wysyła je do połączonych komputerów."""
        try:
            import pd_clipfiles as CF
        except Exception:
            return
        if not CF.available():
            return
        seq = None
        last = None
        while self.running:
            time.sleep(0.5)
            if not (self.sessions and self.f):
                last = None
                continue
            try:
                s = CF.sequence()
                if s == seq:
                    continue
                seq = s
                files = CF.get_files()
                if files and tuple(files) != last:
                    last = tuple(files)
                    self.send({"op": "clip_files", "paths": list(files)})
            except Exception:
                pass

    def _event(self, m):
        ev = m.get("ev")
        self.connected = True
        if ev == "sessions":
            self.sessions = {_SessionProxy(self, d) for d in m.get("list", [])}
            self.on_sessions()
        elif ev == "status":
            self.direct_status = "usługa • " + m.get("direct", "")
            self.relay_status = m.get("relay", "")
            self.agent_version = m.get("version", "?")
            if not self._update_asked:
                try:
                    import pd_update
                    older = m.get("version") is None or pd_update.newer(VERSION, m["version"])
                except Exception:
                    older = False
                if older:
                    self._update_asked = True
                    self.log(time.strftime("%H:%M:%S  ") + f"Usługa ma starszą wersję ({self.agent_version}) – "
                             f"aktualizuję ją do {VERSION}")
                    self.send({"op": "update"})
            self.on_status()
        elif ev == "log":
            self.log(m.get("text", ""))
        elif ev == "chat":
            s = next((x for x in self.sessions if x.id == m.get("sid")), None)
            if s:
                self.on_chat(s, m.get("text", ""))
        elif ev == "ask":
            def answer(ok, remember=False, rid=m.get("rid")):
                self.send({"op": "answer", "rid": rid, "ok": bool(ok), "remember": bool(remember)})
            self.on_ask(m.get("client", "?"), m.get("peer", ""), m.get("code", ""), answer, bool(m.get("device")))
