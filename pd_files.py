"""PilotDesk – menedżer plików w stylu Eksploratora Windows i przeciąganie plików (drag & drop).

Każdy panel (ten komputer / komputer zdalny) ma drzewo folderów („Ten komputer” → Pulpit, Dokumenty, Pobrane,
dyski → foldery, rozwijane strzałkami) i listę z kolumnami Nazwa / Data modyfikacji / Typ / Rozmiar.
Pliki przenosi się przeciągając je między panelami albo z Eksploratora Windows na panel komputera zdalnego.
"""
import os
import shutil
import sys
import time
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

import pd_theme as T
import pd_ui as U
from pd_common import human_size, list_dir

ROOT = ""  # ścieżka „Ten komputer”
_dnd_loaded = {"ok": None}


# --------------------------------------------------------------------------- przeciąganie z Eksploratora

def enable_file_drop(widget, on_drop):
    """Pozwala upuścić na `widget` pliki przeciągnięte z Eksploratora Windows (biblioteka tkdnd).
    on_drop(lista_ścieżek, x_ekranu, y_ekranu) – wołane w wątku okna. Zwraca False, gdy tkdnd niedostępne."""
    if _dnd_loaded["ok"] is None:
        try:
            from tkinterdnd2 import TkinterDnD
            TkinterDnD._require(widget.winfo_toplevel())
            _dnd_loaded["ok"] = True
        except Exception:
            _dnd_loaded["ok"] = False
    if not _dnd_loaded["ok"]:
        return False

    def _drop(data, x, y):
        try:
            paths = [p for p in widget.tk.splitlist(data) if p]
        except Exception:
            paths = [data]
        try:
            xi, yi = int(float(x)), int(float(y))
        except ValueError:
            xi, yi = widget.winfo_pointerx(), widget.winfo_pointery()
        widget.after(1, lambda: on_drop(paths, xi, yi))
        return "copy"

    try:
        drop_cmd = widget.register(_drop)
        pos_cmd = widget.register(lambda *a: "copy")
        widget.tk.call("tkdnd::drop_target", "register", widget._w, "DND_Files")
        widget.tk.call("bind", widget._w, "<<Drop>>", f"{drop_cmd} %D %X %Y")
        widget.tk.call("bind", widget._w, "<<DropPosition>>", f"{pos_cmd} %X %Y")
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- ikony w stylu Windows

_icons = {}


def _draw_icon(kind, px):
    s = 4  # rysujemy 4× większe i zmniejszamy – gładkie krawędzie
    n = px * s
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def R(x0, y0, x1, y1, fill, r=0, outline=None):
        d.rounded_rectangle([x0 * n, y0 * n, x1 * n, y1 * n], radius=r * n, fill=fill, outline=outline,
                            width=max(1, s) if outline else 0)

    if kind in ("folder", "folder_open"):
        R(0.06, 0.18, 0.46, 0.34, "#D9A740", 0.04)  # zakładka
        R(0.06, 0.26, 0.94, 0.84, "#E8B84A", 0.06)  # tył
        R(0.06, 0.36, 0.94, 0.86, "#F6CF62", 0.06)  # przód
    elif kind == "file":
        d.polygon([(0.2 * n, 0.06 * n), (0.62 * n, 0.06 * n), (0.82 * n, 0.26 * n), (0.82 * n, 0.94 * n),
                   (0.2 * n, 0.94 * n)], fill="#F2F2F4", outline="#9A9AA3")
        d.polygon([(0.62 * n, 0.06 * n), (0.62 * n, 0.26 * n), (0.82 * n, 0.26 * n)], fill="#C9C9CF")
    elif kind in ("drive", "usb", "network", "dvd"):
        R(0.08, 0.34, 0.92, 0.76, "#B8BCC6", 0.08)
        R(0.08, 0.58, 0.92, 0.76, "#8E939E", 0.08)
        R(0.68, 0.64, 0.80, 0.70, {"usb": "#3DD68C", "network": "#60A5FA"}.get(kind, "#3DD68C"), 0.02)
    elif kind == "pc":
        R(0.06, 0.14, 0.94, 0.70, "#5B6170", 0.06)
        R(0.11, 0.19, 0.89, 0.64, "#3B82F6", 0.03)
        R(0.40, 0.70, 0.60, 0.80, "#5B6170")
        R(0.26, 0.80, 0.74, 0.86, "#5B6170", 0.02)
    elif kind == "desktop":
        R(0.08, 0.18, 0.92, 0.74, "#2563EB", 0.06)
        R(0.08, 0.62, 0.92, 0.74, "#1E40AF", 0.04)
        R(0.36, 0.76, 0.64, 0.84, "#64748B", 0.02)
    elif kind == "downloads":
        R(0.06, 0.26, 0.94, 0.86, "#E8B84A", 0.06)
        d.polygon([(0.38 * n, 0.08 * n), (0.62 * n, 0.08 * n), (0.62 * n, 0.44 * n), (0.78 * n, 0.44 * n),
                   (0.5 * n, 0.74 * n), (0.22 * n, 0.44 * n), (0.38 * n, 0.44 * n)], fill="#2563EB")
    elif kind == "documents":
        R(0.06, 0.26, 0.94, 0.86, "#E8B84A", 0.06)
        R(0.26, 0.10, 0.74, 0.66, "#F2F2F4", 0.03, outline="#9A9AA3")
        for y in (0.24, 0.34, 0.44):
            R(0.34, y, 0.66, y + 0.04, "#60A5FA")
    elif kind == "home":
        R(0.06, 0.26, 0.94, 0.86, "#E8B84A", 0.06)
        d.ellipse([0.38 * n, 0.36 * n, 0.62 * n, 0.58 * n], fill="#475569")
    return im.resize((px, px), Image.LANCZOS)


def icon(kind, px):
    key = (kind, px)
    if key not in _icons:
        _icons[key] = ImageTk.PhotoImage(_draw_icon(kind, px))
    return _icons[key]


TYPES = {
    ".txt": "Dokument tekstowy", ".log": "Dokument tekstowy", ".pdf": "Dokument PDF", ".doc": "Dokument Word",
    ".docx": "Dokument Word", ".xls": "Arkusz Excel", ".xlsx": "Arkusz Excel", ".csv": "Plik CSV",
    ".ppt": "Prezentacja PowerPoint", ".pptx": "Prezentacja PowerPoint", ".exe": "Aplikacja", ".msi": "Instalator",
    ".zip": "Archiwum ZIP", ".rar": "Archiwum RAR", ".7z": "Archiwum 7-Zip", ".lnk": "Skrót",
    ".mp4": "Plik wideo", ".mkv": "Plik wideo", ".avi": "Plik wideo", ".mov": "Plik wideo",
    ".mp3": "Plik audio", ".wav": "Plik audio", ".flac": "Plik audio",
    ".psd": "Plik Photoshop", ".ai": "Plik Illustrator", ".svg": "Grafika SVG", ".eps": "Grafika EPS",
}


def file_type(e):
    if e.get("dir"):
        return {"drive": "Dysk lokalny", "usb": "Dysk wymienny", "network": "Dysk sieciowy", "dvd": "Napęd DVD"}.get(
            e.get("kind"), "Folder plików")
    ext = os.path.splitext(e["name"])[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"):
        return f"Obraz {ext[1:].upper()}"
    return TYPES.get(ext, f"Plik {ext[1:].upper()}" if ext else "Plik")


def entry_icon_kind(e):
    if not e.get("dir"):
        return "file"
    return {"desktop": "desktop", "downloads": "downloads", "documents": "documents", "home": "home",
            "drive": "drive", "usb": "usb", "network": "network", "dvd": "dvd"}.get(e.get("kind"), "folder")


def _style(widget, sc):
    st = ttk.Style(widget)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    d = U.dark()
    bg = "#111114" if d else "#FFFFFF"
    fg = "#EDEDF0" if d else "#09090B"
    muted = "#8A8A93"
    sel = "#2B2D35" if d else "#CCE4F7"
    rh = int(26 * sc)
    for name in ("PDX.Treeview", "PDN.Treeview"):
        st.configure(name, background=bg, fieldbackground=bg, foreground=fg, rowheight=rh, borderwidth=0,
                     font=(T.SANS, 10), indent=int(14 * sc))
        st.map(name, background=[("selected", sel)], foreground=[("selected", fg)])
        st.layout(name, [("Treeview.treearea", {"sticky": "nswe"})])
    st.configure("PDX.Treeview.Heading", background=bg, foreground=muted, relief="flat", borderwidth=0,
                 font=(T.SANS, 9), padding=(8, 5))
    st.map("PDX.Treeview.Heading", background=[("active", "#1B1B1F" if d else "#F0F0F2")])
    st.configure("PD.TPanedwindow", background="#26262B" if d else "#E4E4E7")
    st.configure("Sash", sashthickness=max(3, int(4 * sc)), gripcount=0, background="#26262B" if d else "#E4E4E7",
                 lightcolor="#26262B" if d else "#E4E4E7", bordercolor="#26262B" if d else "#E4E4E7")
    return bg


# --------------------------------------------------------------------------- panel „Eksplorator”

class ExplorerPane(ctk.CTkFrame):
    """lister(ścieżka, callback(wynik)) – asynchronicznie (dla komputera zdalnego) albo od razu (lokalnie)."""

    def __init__(self, master, title, lister, manager, side):
        super().__init__(master, fg_color=T.SURFACE, corner_radius=12, border_width=1, border_color=T.BORDER)
        self.lister, self.mgr, self.side = lister, manager, side
        self.path = None
        self.parent_path = ""
        self.history = []
        self.entries = {}
        self.sort = ("name", False)
        self.last_result = None
        sc = ctk.ScalingTracker.get_widget_scaling(self)
        self.isz = max(16, int(18 * sc))
        bg = _style(self, sc)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(10, 4))
        U.label(head, title.upper(), 11, color=T.TEXT_3, mono=True).pack(side="left")
        self.count_lbl = U.label(head, "", 11, color=T.TEXT_3)
        self.count_lbl.pack(side="right")
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=10, pady=(0, 8))
        U.icon_button(nav, "arrow_left", self.go_back, tip="Wstecz", width=30, height=30).pack(side="left")
        U.icon_button(nav, "arrow_up", self.go_up, tip="Folder wyżej (Backspace)", width=30, height=30).pack(side="left")
        U.icon_button(nav, "refresh", self.refresh, tip="Odśwież (F5)", width=30, height=30).pack(side="left")
        self.path_e = U.entry(nav, "", height=30, size=12)
        self.path_e.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.path_e.bind("<Return>", lambda e: self.open(self.path_e.get().strip()))
        U.hairline(self, fill="x", padx=1)

        pw = ttk.PanedWindow(self, orient="horizontal", style="PD.TPanedwindow")
        pw.pack(fill="both", expand=True, padx=1, pady=(0, 6))
        # --- drzewo folderów
        nf = tk.Frame(pw, bg=bg)
        self.nav = ttk.Treeview(nf, show="tree", selectmode="browse", style="PDN.Treeview")
        nsb = ctk.CTkScrollbar(nf, command=self.nav.yview, width=10)
        self.nav.configure(yscrollcommand=nsb.set)
        self.nav.pack(side="left", fill="both", expand=True)
        nsb.pack(side="right", fill="y")
        self.nav.column("#0", width=int(210 * sc), stretch=True)
        pw.add(nf, weight=1)
        # --- lista plików
        lf = tk.Frame(pw, bg=bg)
        cols = ("mtime", "type", "size")
        self.list = ttk.Treeview(lf, columns=cols, selectmode="extended", style="PDX.Treeview")
        for col, text, w, anchor in (("#0", "Nazwa", 250, "w"), ("mtime", "Data modyfikacji", 130, "w"),
                                     ("type", "Typ", 120, "w"), ("size", "Rozmiar", 80, "e")):
            key = {"#0": "name"}.get(col, col)
            self.list.heading(col, text=text, anchor=anchor, command=lambda k=key: self._sort_by(k))
            self.list.column(col, width=int(w * sc), anchor=anchor, stretch=(col == "#0"))
        lsb = ctk.CTkScrollbar(lf, command=self.list.yview, width=10)
        self.list.configure(yscrollcommand=lsb.set)
        self.list.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        pw.add(lf, weight=3)

        self.nav_nodes = {}  # ścieżka -> iid w drzewie
        self.root_iid = self.nav.insert("", "end", text="  Ten komputer", image=icon("pc", self.isz), open=True)
        self.nav_nodes[ROOT] = self.root_iid
        self.nav.bind("<<TreeviewOpen>>", self._nav_expand)
        self.nav.bind("<<TreeviewSelect>>", self._nav_select)
        self.list.bind("<Double-1>", self._activate)
        self.list.bind("<Return>", self._activate)
        self.list.bind("<BackSpace>", lambda e: self.go_up())
        self.list.bind("<Delete>", lambda e: self.mgr.delete(self))
        self.list.bind("<F2>", lambda e: self.mgr.rename(self))
        self.list.bind("<F5>", lambda e: self.refresh())
        self.list.bind("<Control-a>", lambda e: (self.list.selection_set(self.list.get_children()), "break")[1])
        self.list.bind("<Button-3>", self._context)
        for w in (self.list, self.nav):
            w.bind("<ButtonPress-1>", self._press, add="+")
            w.bind("<B1-Motion>", self._motion, add="+")
            w.bind("<ButtonRelease-1>", self._release, add="+")
        self._drag = None
        self._suppress_nav = False

    # ------------------------------------------------------------ nawigacja
    def open(self, path, remember=True):
        if remember and self.path is not None and path != self.path:
            self.history.append(self.path)
            self.history = self.history[-50:]
        self.path_e.delete(0, "end")
        self.path_e.insert(0, path or "Ten komputer")
        self.count_lbl.configure(text="wczytuję…")
        self.lister(path, lambda r, p=path: self._show(r, p))

    def refresh(self):
        if self.path is not None:
            self.open(self.path, remember=False)

    def go_back(self):
        if self.history:
            self.open(self.history.pop(), remember=False)

    def go_up(self):
        if self.path:
            self.open(self.parent_path)

    def _show(self, r, requested):
        if not self.winfo_exists():
            return
        self.last_result = r
        self.path = r.get("path", requested) if not r.get("error") else requested
        self.parent_path = r.get("parent", "")
        self.path_e.delete(0, "end")
        self.path_e.insert(0, self.path or "Ten komputer")
        if self.path == ROOT and not r.get("error"):
            self._fill_nav_children(self.root_iid, r.get("entries", []))
        self._fill_list(r)
        self._select_nav(self.path)

    def _fill_list(self, r):
        self.list.delete(*self.list.get_children())
        self.entries = {}
        if r.get("error"):
            self.list.insert("", "end", text="  " + str(r["error"])[:200])
            self.count_lbl.configure(text="błąd")
            return
        key, rev = self.sort
        ents = list(r.get("entries", []))
        if self.path != ROOT:
            sk = {"name": lambda e: e["name"].lower(), "mtime": lambda e: e.get("mtime", 0),
                  "type": lambda e: file_type(e).lower(), "size": lambda e: e.get("size", 0)}[key]
            ents.sort(key=sk, reverse=rev)
            ents.sort(key=lambda e: not e["dir"])  # foldery zawsze na górze
        for e in ents:
            mt = time.strftime("%d.%m.%Y %H:%M", time.localtime(e["mtime"])) if e.get("mtime") else ""
            iid = self.list.insert("", "end", text="  " + e["name"], image=icon(entry_icon_kind(e), self.isz),
                                   values=(mt, file_type(e), "" if e["dir"] else human_size(e.get("size", 0))))
            self.entries[iid] = e
        n = len(ents)
        self.count_lbl.configure(text=f"{n} element" + ("" if n == 1 else "y" if 2 <= n % 10 <= 4 and not
                                                         12 <= n % 100 <= 14 else "ów"))

    def _sort_by(self, key):
        self.sort = (key, not self.sort[1] if self.sort[0] == key else False)
        if self.last_result:
            self._fill_list(self.last_result)

    # ------------------------------------------------------------ drzewo folderów
    def _fill_nav_children(self, iid, entries):
        for c in self.nav.get_children(iid):
            self._forget_nav(c)
            self.nav.delete(c)
        for e in entries:
            if not e.get("dir"):
                continue
            child = self.nav.insert(iid, "end", text="  " + e["name"], image=icon(entry_icon_kind(e), self.isz),
                                    values=(e["path"],))
            self.nav_nodes.setdefault(e["path"], child)
            self.nav.insert(child, "end", text="…")  # strzałka „rozwiń”, zanim wczytamy podfoldery

    def _forget_nav(self, iid):
        for c in self.nav.get_children(iid):
            self._forget_nav(c)
        vals = self.nav.item(iid, "values")
        if vals and self.nav_nodes.get(vals[0]) == iid:
            del self.nav_nodes[vals[0]]

    def _nav_path(self, iid):
        if iid == self.root_iid:
            return ROOT
        vals = self.nav.item(iid, "values")
        return vals[0] if vals else None

    def _nav_expand(self, _e=None):
        iid = self.nav.focus()
        path = self._nav_path(iid)
        if path is None or iid == self.root_iid:
            return
        kids = self.nav.get_children(iid)
        if len(kids) == 1 and self.nav.item(kids[0], "text") == "…":
            self.lister(path, lambda r, i=iid: self.winfo_exists() and self.nav.exists(i) and
                        self._fill_nav_children(i, [] if r.get("error") else r.get("entries", [])))

    def _nav_select(self, _e=None):
        if self._suppress_nav:
            return
        sel = self.nav.selection()
        if sel:
            path = self._nav_path(sel[0])
            if path is not None and path != self.path:
                self.open(path)

    def _select_nav(self, path):
        iid = self.nav_nodes.get(path)
        if iid and self.nav.exists(iid):
            self._suppress_nav = True
            try:
                self.nav.selection_set(iid)
                self.nav.see(iid)
            finally:
                self.after(50, lambda: setattr(self, "_suppress_nav", False))

    # ------------------------------------------------------------ zaznaczenie i działania
    def selected(self):
        return [self.entries[i] for i in self.list.selection() if i in self.entries]

    def _activate(self, _e=None):
        sel = self.selected()
        if len(sel) == 1 and sel[0]["dir"]:
            self.open(sel[0]["path"])

    def folder_at(self, x_root, y_root):
        """Folder docelowy pod kursorem: folder z listy/drzewa albo bieżący folder."""
        w = self.winfo_containing(x_root, y_root)
        if w is self.list:
            iid = self.list.identify_row(y_root - self.list.winfo_rooty())
            e = self.entries.get(iid)
            if e and e["dir"]:
                return e["path"]
            return self.path
        if w is self.nav:
            iid = self.nav.identify_row(y_root - self.nav.winfo_rooty())
            p = self._nav_path(iid) if iid else None
            return p if p else self.path
        return self.path

    def contains(self, x_root, y_root):
        w = self.winfo_containing(x_root, y_root)
        while w is not None:
            if w is self:
                return True
            w = w.master
        return False

    def _context(self, e):
        iid = self.list.identify_row(e.y)
        if iid and iid not in self.list.selection():
            self.list.selection_set(iid)
        sel = self.selected()
        other = "Wyślij na komputer zdalny" if self.side == "local" else "Pobierz na ten komputer"
        items = []
        if len(sel) == 1 and sel[0]["dir"]:
            items.append(("Otwórz", lambda: self.open(sel[0]["path"])))
        if sel:
            items.append((other + " →" if self.side == "local" else "← " + other, lambda: self.mgr.transfer(self, sel)))
            items.append(None)
        if self.path:
            items.append(("Nowy folder", lambda: self.mgr.mkdir(self)))
        if len(sel) == 1:
            items.append(("Zmień nazwę (F2)", lambda: self.mgr.rename(self)))
        if sel:
            items.append(("Usuń (Delete)", lambda: self.mgr.delete(self)))
        items += [None, ("Odśwież (F5)", self.refresh)]
        m = tk.Menu(self, tearoff=False)
        d = U.dark()
        m.configure(bg="#141417" if d else "#FFFFFF", fg="#EDEDF0" if d else "#09090B",
                    activebackground="#232328" if d else "#F0F0F2", activeforeground="#FFFFFF" if d else "#09090B",
                    bd=1, relief="solid", font=(T.SANS, 10), activeborderwidth=0)
        for it in items:
            if it is None:
                m.add_separator()
            else:
                m.add_command(label="  " + it[0] + "      ", command=it[1])
        m.tk_popup(e.x_root, e.y_root)

    # ------------------------------------------------------------ przeciąganie między panelami
    def _press(self, e):
        self._drag = {"x": e.x_root, "y": e.y_root, "w": e.widget, "on": False, "tip": None}

    def _motion(self, e):
        d = self._drag
        if not d or d["w"] is not self.list:
            return
        if not d["on"] and abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) > 8:
            sel = self.selected()
            if not sel:
                self._drag = None
                return
            d["on"] = True
            d["items"] = sel
            tip = tk.Toplevel(self)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            n = len(sel)
            txt = sel[0]["name"] if n == 1 else f"{n} elementy" if 2 <= n <= 4 else f"{n} elementów"
            tk.Label(tip, text=("  ↗  " + txt[:40] + "  "), bg="#2563EB", fg="#FFFFFF",
                     font=(T.SANS, 10)).pack()
            d["tip"] = tip
        if d["on"] and d["tip"]:
            d["tip"].geometry(f"+{e.x_root + 14}+{e.y_root + 10}")

    def _release(self, e):
        d, self._drag = self._drag, None
        if not d or not d["on"]:
            return
        try:
            d["tip"].destroy()
        except Exception:
            pass
        self.mgr.dropped_from_pane(self, d["items"], e.x_root, e.y_root)


# --------------------------------------------------------------------------- okno menedżera plików

class FileManager(ctk.CTkToplevel):
    def __init__(self, sess):
        super().__init__(sess.win)
        self.sess = sess
        self.title(f"Pliki – {sess.remote_name}")
        self.geometry("1360x800")
        self.minsize(980, 560)
        self.configure(fg_color=T.BG)
        T.apply_window_icon(self)
        T.apply_dark_title_bar(self, U.dark())
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 0))
        U.label(top, "Przeciągnij pliki między panelami albo z Eksploratora Windows na panel komputera zdalnego.",
                12, color=T.TEXT_3).pack(side="left")
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(8, 6))
        body.grid_columnconfigure(0, weight=1, uniform="p")
        body.grid_columnconfigure(2, weight=1, uniform="p")
        body.grid_rowconfigure(0, weight=1)
        self.local = ExplorerPane(body, "ten komputer", self._list_local, self, "local")
        self.local.grid(row=0, column=0, sticky="nsew")
        mid = ctk.CTkFrame(body, fg_color="transparent", width=56)
        mid.grid(row=0, column=1, sticky="ns", padx=8)
        b1 = U.icon_button(mid, "arrow_right", lambda: self.transfer(self.local, self.local.selected()),
                           tip="Wyślij zaznaczone na komputer zdalny", width=44, height=44, size=18)
        b1.pack(pady=(160, 8))
        U.icon_button(mid, "arrow_left", lambda: self.transfer(self.remote, self.remote.selected()),
                      tip="Pobierz zaznaczone na ten komputer", width=44, height=44, size=18).pack()
        self.remote = ExplorerPane(body, sess.remote_name, self._list_remote, self, "remote")
        self.remote.grid(row=0, column=2, sticky="nsew")
        for w in (self.remote.list, self.remote.nav):
            enable_file_drop(w, lambda paths, x, y: self._external_drop(paths, x, y))
        for w in (self.local.list, self.local.nav):
            enable_file_drop(w, lambda paths, x, y: self._toast("Upuść pliki na panel komputera zdalnego (po prawej), "
                                                                "aby je tam wysłać."))
        U.section(self, "transfery", padx=16, pady=(4, 4))
        self.xlist = ctk.CTkScrollableFrame(self, fg_color="transparent", height=84)
        self.xlist.pack(fill="x", padx=12, pady=(0, 12))
        self.xempty = U.label(self.xlist, "Brak transferów. Przeciągnij pliki albo użyj strzałek → ←.", 12,
                              color=T.TEXT_3)
        self.xempty.pack(anchor="w", padx=6, pady=4)
        self.xrows = {}
        for tid, t in sess.transfers.items():
            self.show_transfer(tid, t)
        self._refresh_pending = False
        self.local.open(ROOT)
        self.remote.open(ROOT)

    # ------------------------------------------------------------ źródła list
    def _list_local(self, path, cb):
        try:
            r = list_dir(path)
        except Exception as e:
            r = {"path": path, "parent": os.path.dirname(path.rstrip("\\/")), "entries": [], "error": str(e)}
        cb(r)

    def _list_remote(self, path, cb):
        self.sess.request_ls(path, lambda r: self.winfo_exists() and cb(r))

    # ------------------------------------------------------------ transfery
    def transfer(self, pane, items, dest=None):
        if not items:
            self._toast("Zaznacz pliki lub foldery.")
            return
        if pane is self.local:
            dest = dest if dest is not None else self.remote.path
            if not dest:
                self._toast("Po prawej otwórz najpierw folder docelowy (np. Pulpit).")
                return
            self.sess.upload([e["path"] for e in items], dest=dest)
            self.remote_refresh_soon()
        else:
            dest = dest if dest is not None else self.local.path
            if not dest:
                self._toast("Po lewej otwórz najpierw folder docelowy (np. Pobrane).")
                return
            for e in items:
                self.sess.download(e["path"], dest)

    def dropped_from_pane(self, src, items, x, y):
        dst = self.remote if src is self.local else self.local
        if dst.contains(x, y):
            self.transfer(src, items, dest=dst.folder_at(x, y))

    def _external_drop(self, paths, x, y):
        dest = self.remote.folder_at(x, y)
        if not dest:
            self._toast("Otwórz najpierw folder na komputerze zdalnym (np. Pulpit), potem upuść pliki.")
            return
        self.sess.upload([p for p in paths if os.path.exists(p)], dest=dest)
        self.remote_refresh_soon()

    def show_transfer(self, tid, t):
        if not self.winfo_exists():
            return
        if self.xempty:
            self.xempty.destroy()
            self.xempty = None
        row = self.xrows.get(tid)
        if not row:
            first = next((w for w in self.xlist.winfo_children() if w.winfo_manager()), None)
            row = ctk.CTkFrame(self.xlist, fg_color="transparent")
            row.pack(fill="x", pady=1, **({"before": first} if first is not None else {}))
            U.label(row, "↑" if t["dir"] == "up" else "↓", 12, color=T.TEXT_3, mono=True, width=16).pack(
                side="left", padx=(6, 6))
            row.name = U.label(row, os.path.basename(t["name"])[:44], 12, width=300, anchor="w")
            row.name.pack(side="left")
            row.bar = ctk.CTkProgressBar(row, width=180, height=4, progress_color=T.TEXT_2, fg_color=T.SURFACE_3)
            row.bar.pack(side="left", padx=10)
            row.info = U.label(row, "", 11, color=T.TEXT_3, anchor="w", mono=True)
            row.info.pack(side="left", fill="x", expand=True)
            self.xrows[tid] = row
        pct = t["done"] / t["size"] if t["size"] else 1.0
        row.bar.set(pct)
        st = t["status"]
        done = st.startswith("zapisano") or st == "wysłano"
        row.bar.configure(progress_color=T.GREEN if done else (T.RED if st.startswith("błąd") else T.TEXT_2))
        text = f"{pct * 100:.0f}%  {human_size(t['done'])} / {human_size(t['size'])}" if st == "trwa" else st
        row.info.configure(text=text[:90], text_color=T.RED if st.startswith("błąd") else T.TEXT_3)
        if done:
            if t["dir"] == "down":
                self.local.refresh()
            else:
                self.remote_refresh_soon()

    def remote_refresh_soon(self):
        if not self._refresh_pending:
            self._refresh_pending = True

            def go():
                self._refresh_pending = False
                if self.winfo_exists():
                    self.remote.refresh()
            self.after(900, go)

    # kompatybilność ze starym interfejsem (SessionView woła te metody)
    def local_refresh(self):
        if self.winfo_exists():
            self.local.refresh()

    def refresh_both(self):
        self.local.refresh()
        self.remote.refresh()

    def _toast(self, t, kind="warn"):
        U.Toast(self, t, kind)

    # ------------------------------------------------------------ operacje na plikach
    @staticmethod
    def _join(base, name):
        sep = "\\" if ("\\" in base or (len(base) >= 2 and base[1] == ":")) else "/"
        return base.rstrip("\\/") + sep + name

    def _op_done(self, r):
        if not r.get("ok"):
            self._toast(r.get("error", "Błąd"), "error")
        self.remote.refresh()

    def mkdir(self, pane):
        if not pane.path:
            return
        name = U.ask_string(self, "Nowy folder", "Nazwa folderu:", "Nowy folder", icon="folder")
        if not name:
            return
        path = self._join(pane.path, name)
        if pane is self.remote:
            self.sess.request_op("mkdir", self._op_done, path=path)
        else:
            try:
                os.makedirs(path, exist_ok=False)
            except OSError as e:
                self._toast(str(e), "error")
            pane.refresh()

    def rename(self, pane):
        sel = pane.selected()
        if len(sel) != 1 or not pane.path:
            return
        name = U.ask_string(self, "Zmień nazwę", "Nowa nazwa:", sel[0]["name"])
        if not name or name == sel[0]["name"]:
            return
        new = self._join(pane.path, name)
        if pane is self.remote:
            self.sess.request_op("rename", self._op_done, path=sel[0]["path"], new=new)
        else:
            try:
                os.rename(sel[0]["path"], new)
            except OSError as e:
                self._toast(str(e), "error")
            pane.refresh()

    def delete(self, pane):
        sel = pane.selected()
        if not sel or not pane.path:
            return
        names = ", ".join(e["name"] for e in sel[:5]) + (" …" if len(sel) > 5 else "")
        if pane is self.remote:
            if U.confirm(self, "Usunąć na komputerze zdalnym?", f"{names}\nPliki zostaną usunięte trwale (bez kosza).",
                         "Usuń", danger=True, icon="trash"):
                for e in sel:
                    self.sess.request_op("delete", self._op_done, path=e["path"])
        else:
            if U.confirm(self, "Przenieść do kosza?" if sys.platform == "win32" else "Usunąć?", names, "Usuń",
                         danger=True, icon="trash"):
                for e in sel:
                    try:
                        _delete_local(e["path"])
                    except OSError as ex:
                        self._toast(str(ex), "error")
                pane.refresh()


def _delete_local(path):
    """Windows: do kosza (jak w Eksploratorze). Inaczej – trwale."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
        op = SHFILEOPSTRUCTW(None, 3, path + "\0", None, 0x0040 | 0x0010 | 0x0400, False, None, None)
        # FO_DELETE, FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI
        r = ctypes.WinDLL("shell32").SHFileOperationW(ctypes.byref(op))
        if r != 0:
            raise OSError(f"Nie udało się usunąć ({r})")
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
