"""PilotDesk – automatyczne aktualizacje.

Źródło aktualizacji (Ustawienia):
  * „właściciel/repozytorium” na GitHubie – brana jest ostatnia wersja z zakładki Releases
    (plik PilotDesk.exe + opcjonalnie PilotDesk.exe.sha256 – tworzy je dołączony workflow),
  * albo adres URL pliku JSON: {"version": "3.1", "url": "https://.../PilotDesk.exe", "sha256": "..."}.
"""
import hashlib
import json
import os
import re
import tempfile
import urllib.request

UA = {"User-Agent": "PilotDesk-updater", "Accept": "application/vnd.github+json"}


def parse_version(v):
    nums = re.findall(r"\d+", str(v))
    return tuple(int(n) for n in nums[:4]) or (0,)


def newer(a, b):
    return parse_version(a) > parse_version(b)


def _get(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def check(source):
    """Zwraca {"version", "url", "sha256"} albo None."""
    source = (source or "").strip()
    if not source:
        return None
    if "://" in source:
        d = json.loads(_get(source))
        return {"version": str(d["version"]), "url": d["url"], "sha256": d.get("sha256", ""),
                "notes": d.get("notes", ""), "size": int(d.get("size", 0))}
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", source):
        raise ValueError("Źródło aktualizacji: wpisz „właściciel/repozytorium” albo adres URL.")
    rel = json.loads(_get(f"https://api.github.com/repos/{source}/releases/latest"))
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    sizes = {a["name"]: a.get("size", 0) for a in rel.get("assets", [])}
    if "PilotDesk.exe" not in assets:
        return None
    sha = ""
    if "PilotDesk.exe.sha256" in assets:
        try:
            sha = _get(assets["PilotDesk.exe.sha256"]).decode().split()[0].strip().lower()
        except Exception:
            sha = ""
    return {"version": rel.get("tag_name", "0").lstrip("vV"), "url": assets["PilotDesk.exe"], "sha256": sha,
            "notes": clean_notes(rel.get("body") or ""), "size": sizes.get("PilotDesk.exe", 0),
            "date": (rel.get("published_at") or "")[:10]}


def clean_notes(text):
    """Opis wydania bez technicznych dopisków."""
    out = [ln for ln in text.replace("\r", "").splitlines()
           if not ln.startswith(("Co-Authored-By", "Claude-Session"))]
    return "\n".join(out).strip()


def download(info, dest=None, progress=None):
    dest = dest or os.path.join(tempfile.gettempdir(), f"PilotDesk-{parse_version(info['version'])}.exe")
    h = hashlib.sha256()
    tmp = dest + ".part"
    with urllib.request.urlopen(urllib.request.Request(info["url"], headers={"User-Agent": UA["User-Agent"]}),
                                timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    if info.get("sha256") and h.hexdigest().lower() != info["sha256"].lower():
        os.remove(tmp)
        raise ValueError("Suma kontrolna pobranego pliku się nie zgadza – aktualizacja przerwana.")
    if os.path.exists(dest):
        os.remove(dest)
    os.replace(tmp, dest)
    return dest
