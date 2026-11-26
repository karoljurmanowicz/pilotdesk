"""PilotDesk – dziennik zdarzeń i wykrywanie zawieszeń.

Plik: %LOCALAPPDATA%\\PilotDesk\\pilotdesk.log (Linux/macOS: ~/.local/share/pilotdesk/pilotdesk.log).
Zapisuje: zdarzenia programu, błędy w wątkach i w oknie, a gdy okno przestaje odpowiadać na dłużej niż
4 sekundy – co dokładnie robi każdy wątek (to pozwala znaleźć przyczynę zawieszenia).
"""
import logging
import logging.handlers
import os
import sys
import threading
import time
import traceback

_log = logging.getLogger("pilotdesk")
_ready = False


def log_dir():
    if sys.platform == "win32":
        d = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "PilotDesk")
    else:
        d = os.path.join(os.path.expanduser("~"), ".local", "share", "pilotdesk")
    os.makedirs(d, exist_ok=True)
    return d


def log_path():
    return os.path.join(log_dir(), "pilotdesk.log")


def setup():
    global _ready
    if _ready:
        return _log
    try:
        h = logging.handlers.RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
        _log.addHandler(h)
        _log.setLevel(logging.INFO)
    except Exception:
        pass

    def thread_hook(args):
        _log.error("Błąd w wątku %s: %s", getattr(args.thread, "name", "?"),
                   "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    threading.excepthook = thread_hook
    _ready = True
    try:
        from pd_common import VERSION
        _log.info("===== PilotDesk %s start (%s, Python %s)", VERSION, sys.platform, sys.version.split()[0])
    except Exception:
        pass
    return _log


def info(msg, *a):
    _log.info(msg, *a)


def error(msg, *a):
    _log.error(msg, *a)


def exception(msg):
    _log.error("%s\n%s", msg, traceback.format_exc())


def dump_threads(reason):
    frames = sys._current_frames()
    out = [f"{reason} – stan wątków:"]
    for t in threading.enumerate():
        f = frames.get(t.ident)
        if f is None:
            continue
        out.append(f"--- {t.name}\n" + "".join(traceback.format_stack(f)[-8:]))
    _log.warning("\n".join(out))


class UiWatchdog:
    """Pilnuje, czy okno (pętla Tk) odpowiada. Przy zawieszeniu > 4 s zapisuje stos wszystkich wątków."""

    def __init__(self, root, limit=4.0):
        self.root = root
        self.limit = limit
        self.beat = time.time()
        self.reported = False
        self.root.after(500, self._tick)
        threading.Thread(target=self._watch, name="watchdog", daemon=True).start()

    def _tick(self):
        now = time.time()
        if self.reported:
            _log.warning("Okno znów odpowiada (było zawieszone %.1f s)", now - self.beat)
            self.reported = False
        self.beat = now
        try:
            self.root.after(500, self._tick)
        except Exception:
            pass

    def _watch(self):
        while True:
            time.sleep(1)
            if not self.reported and time.time() - self.beat > self.limit:
                self.reported = True
                dump_threads(f"Okno nie odpowiada od {time.time() - self.beat:.1f} s")
