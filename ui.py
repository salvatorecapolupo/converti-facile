"""Interfaccia di ConvertiFacile 1.1 — Tkinter/ttk interamente ridisegnata.

Scelte per Windows 11: processo "DPI aware" (testo nitido), tema ttk "clam" con stile
unico per tutti i widget (niente mescolanze tk/ttk), elenco file in Treeview con
selezione del formato direttamente nella riga, trascinamento file (se tkinterdnd2 c'è).
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import engine
import formats
from common import Cancelled, ConversionError, Options

APP_NAME = "ConvertiFacile"
VERSION = "1.1"

C = dict(bg="#F5F6F8", card="#FFFFFF", text="#1F2937", muted="#6B7280", accent="#2563EB",
         accent_h="#1D4ED8", accent_p="#1E40AF", border="#D5D9E0", ok="#15803D", err="#B91C1C",
         sel="#DBEAFE", head="#EEF1F5", btn="#E9ECF1", btn_h="#DDE2EA")

try:  # trascinamento file: opzionale, se manca l'app funziona uguale
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except Exception:  # pragma: no cover
    _HAS_DND = False


def _pick_font(root) -> str:
    fams = set(tkfont.families(root))
    for name in ("Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", "DejaVu Sans"):
        if name in fams:
            return name
    return "TkDefaultFont"


def open_path(path: str):
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class App:
    COLS = ("name", "src", "dst", "state")

    def __init__(self, root):
        self.root = root
        root.title(f"{APP_NAME} {VERSION}")
        root.minsize(820, 600)
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        root.geometry(f"{int(940 * self.scale / 1.0)}x{int(680 * self.scale)}")
        root.configure(bg=C["bg"])
        self.family = _pick_font(root)
        self._set_icon()
        self._style()

        self.items = {}            # iid -> dict(path, target, state, msg, outputs)
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.last_dir = None
        self.edit_box = None

        self.dest_mode = tk.StringVar(value="source")
        self.dest_dir = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Documents"))
        self.quality = tk.IntVar(value=90)
        self.strip = tk.BooleanVar(value=False)
        self.overwrite = tk.BooleanVar(value=False)
        self.csv_sep = tk.StringVar(value="Punto e virgola ( ; )")
        self.bulk_target = tk.StringVar()
        self.status = tk.StringVar(value="Aggiungi i file da convertire.")

        self._build()
        self._bind()
        self._refresh()
        self.root.after(100, self._poll)

    # ── stile ──────────────────────────────────────────────
    def _set_icon(self):
        try:
            from PIL import ImageTk
            import icon
            self._icon = ImageTk.PhotoImage(icon.make_icon(64))
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass

    def _style(self):
        f = self.family
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        px = lambda n: int(n * self.scale)
        base = (f, 10)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont"):
            try:
                tkfont.nametofont(name).configure(family=f if name != "TkFixedFont" else "Consolas", size=10)
            except tk.TclError:
                pass
        self.root.option_add("*TCombobox*Listbox.font", base)
        self.root.option_add("*TCombobox*Listbox.background", C["card"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])

        st.configure(".", background=C["bg"], foreground=C["text"], font=base,
                     bordercolor=C["border"], lightcolor=C["bg"], darkcolor=C["bg"], focuscolor=C["bg"])
        st.configure("TFrame", background=C["bg"])
        st.configure("Card.TFrame", background=C["card"], relief="solid", borderwidth=1, bordercolor=C["border"])
        st.configure("TLabel", background=C["bg"], foreground=C["text"])
        st.configure("Card.TLabel", background=C["card"])
        st.configure("Title.TLabel", font=(f, 20, "bold"), foreground=C["accent"])
        st.configure("Muted.TLabel", foreground=C["muted"], font=(f, 9))
        st.configure("CardMuted.TLabel", background=C["card"], foreground=C["muted"], font=(f, 9))
        st.configure("Head.TLabel", background=C["card"], font=(f, 10, "bold"))
        st.configure("TButton", background=C["btn"], foreground=C["text"], padding=(px(14), px(7)),
                     borderwidth=0, relief="flat", focusthickness=0)
        st.map("TButton", background=[("disabled", "#F0F1F4"), ("pressed", C["btn_h"]), ("active", C["btn_h"])],
               foreground=[("disabled", "#9CA3AF")])
        st.configure("Accent.TButton", background=C["accent"], foreground="white", padding=(px(24), px(9)),
                     font=(f, 10, "bold"))
        st.map("Accent.TButton", background=[("disabled", "#93B4F5"), ("pressed", C["accent_p"]), ("active", C["accent_h"])],
               foreground=[("disabled", "white")])
        st.configure("TCheckbutton", background=C["bg"], focuscolor=C["bg"])
        st.configure("TRadiobutton", background=C["bg"], focuscolor=C["bg"])
        st.configure("Card.TCheckbutton", background=C["card"])
        st.configure("TEntry", fieldbackground="white", bordercolor=C["border"], padding=px(5))
        st.configure("TCombobox", fieldbackground="white", background=C["btn"], bordercolor=C["border"],
                     arrowcolor=C["text"], padding=px(5))
        st.map("TCombobox", fieldbackground=[("readonly", "white")], background=[("active", C["btn_h"])])
        st.configure("TScale", background=C["card"], troughcolor=C["border"])
        st.configure("Horizontal.TProgressbar", troughcolor=C["border"], background=C["accent"],
                     bordercolor=C["border"], lightcolor=C["accent"], darkcolor=C["accent"], thickness=px(8))
        st.configure("Treeview", background="white", fieldbackground="white", foreground=C["text"],
                     rowheight=px(36), borderwidth=0, font=base)
        st.map("Treeview", background=[("selected", C["sel"])], foreground=[("selected", C["text"])])
        st.configure("Treeview.Heading", background=C["head"], foreground=C["muted"], relief="flat",
                     font=(f, 9, "bold"), padding=(px(8), px(7)))
        st.map("Treeview.Heading", background=[("active", C["head"])])
        st.configure("Vertical.TScrollbar", background=C["btn"], troughcolor=C["bg"], bordercolor=C["bg"],
                     arrowcolor=C["muted"], relief="flat")

    # ── costruzione ────────────────────────────────────────
    def _build(self):
        pad = int(18 * self.scale)
        outer = ttk.Frame(self.root, padding=(pad, int(14 * self.scale), pad, int(14 * self.scale)))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        # intestazione
        head = ttk.Frame(outer)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(head, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(head, text=f"  v{VERSION}", style="Muted.TLabel").pack(
            side="left", pady=(8, 0))
        ttk.Button(head, text="Formati supportati…", command=self.show_formats).pack(side="right")
        ttk.Button(head, text="Svuota", command=self.clear).pack(side="right", padx=8)
        ttk.Button(head, text="＋  Aggiungi file", command=self.add_files).pack(side="right")

        # elenco file
        box = ttk.Frame(outer, style="Card.TFrame")
        box.grid(row=1, column=0, sticky="nsew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(box, columns=self.COLS, show="headings", selectmode="extended")
        for col, text, w, stretch in (("name", "File", 380, True), ("src", "Formato", 110, False),
                                      ("dst", "Converti in  ▾", 120, False), ("state", "Stato", 190, False)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=int(w * self.scale), minwidth=int(60 * self.scale), stretch=stretch, anchor="w")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("odd", background="#FAFBFC")
        self.tree.tag_configure("ok", foreground=C["ok"])
        self.tree.tag_configure("err", foreground=C["err"])
        self.empty = ttk.Label(box, text="Trascina qui i file da convertire\noppure premi “Aggiungi file”",
                               style="CardMuted.TLabel", justify="center", font=(self.family, 12))
        self.empty.place(relx=0.5, rely=0.5, anchor="center")

        # scheda "formati" (frase + storia)
        info = ttk.Frame(outer, style="Card.TFrame", padding=int(10 * self.scale))
        info.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        info.columnconfigure(0, weight=1)
        self.info_src = ttk.Label(info, text="", style="Card.TLabel", justify="left")
        self.info_dst = ttk.Label(info, text="", style="Card.TLabel", justify="left")
        self.info_src.grid(row=0, column=0, sticky="ew")
        self.info_dst.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        info.bind("<Configure>", lambda e: [w.configure(wraplength=max(200, e.width - 30)) for w in (self.info_src, self.info_dst)])

        # conversione di gruppo + opzioni
        opt = ttk.Frame(outer)
        opt.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(opt, text="Converti la selezione (o tutto) in:").grid(row=0, column=0, sticky="w")
        self.bulk = ttk.Combobox(opt, textvariable=self.bulk_target, state="readonly", width=9)
        self.bulk.grid(row=0, column=1, sticky="w", padx=(8, 24))
        self.bulk.bind("<<ComboboxSelected>>", self._apply_bulk)
        ttk.Label(opt, text="Qualità").grid(row=0, column=2, sticky="e")
        self.qlabel = ttk.Label(opt, text="90", width=4)
        sc = ttk.Scale(opt, from_=40, to=100, variable=self.quality, length=int(130 * self.scale),
                       command=lambda v: self.qlabel.configure(text=str(int(float(v)))))
        sc.grid(row=0, column=3, padx=8)
        self.qlabel.grid(row=0, column=4, sticky="w")
        ttk.Label(opt, text="CSV").grid(row=0, column=5, sticky="e", padx=(18, 6))
        ttk.Combobox(opt, textvariable=self.csv_sep, state="readonly", width=20,
                     values=["Punto e virgola ( ; )", "Virgola ( , )"]).grid(row=0, column=6)
        chk = ttk.Frame(opt)
        chk.grid(row=1, column=0, columnspan=7, sticky="w", pady=(8, 0))
        ttk.Checkbutton(chk, text="Rimuovi metadati dalle immagini (EXIF, GPS)", variable=self.strip).pack(side="left")
        ttk.Checkbutton(chk, text="Sovrascrivi file esistenti", variable=self.overwrite).pack(side="left", padx=18)

        # destinazione
        dest = ttk.Frame(outer)
        dest.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        dest.columnconfigure(2, weight=1)
        ttk.Radiobutton(dest, text="Accanto all'originale", value="source", variable=self.dest_mode,
                        command=self._dest_toggle).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(dest, text="Cartella:", value="custom", variable=self.dest_mode,
                        command=self._dest_toggle).grid(row=0, column=1, sticky="w", padx=(20, 6))
        self.dest_entry = ttk.Entry(dest, textvariable=self.dest_dir)
        self.dest_entry.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        self.dest_btn = ttk.Button(dest, text="Sfoglia…", command=self.pick_dest)
        self.dest_btn.grid(row=0, column=3)
        self._dest_toggle()

        # barra inferiore
        bar = ttk.Frame(outer)
        bar.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        bar.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(bar, mode="determinate")
        self.progress.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(bar, textvariable=self.status, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.open_btn = ttk.Button(bar, text="Apri cartella", command=self.open_output)
        self.open_btn.grid(row=1, column=1, padx=8, pady=(6, 0))
        self.go_btn = ttk.Button(bar, text="Converti", style="Accent.TButton", command=self.start)
        self.go_btn.grid(row=1, column=2, pady=(6, 0))

    def _bind(self):
        t = self.tree
        t.bind("<<TreeviewSelect>>", lambda e: self._refresh())
        t.bind("<Button-1>", self._on_click, add="+")
        t.bind("<Double-1>", self._on_double)
        t.bind("<Delete>", lambda e: self.remove_selected())
        t.bind("<MouseWheel>", lambda e: self._close_edit())
        self.root.bind("<Control-o>", lambda e: self.add_files())
        self.root.bind("<F1>", lambda e: self.show_formats())
        self.root.bind("<Return>", lambda e: self.start() if str(self.go_btn["state"]) != "disabled" and self.root.focus_get() is self.tree else None)
        if _HAS_DND:
            try:
                for w in (self.tree, self.empty):
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    # ── gestione elenco ────────────────────────────────────
    def _on_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))

    def add_files(self):
        exts = formats.all_input_exts()
        patt = " ".join("*" + e for e in exts)
        paths = filedialog.askopenfilenames(
            title="Scegli i file da convertire",
            filetypes=[("Tutti i formati supportati", patt), ("Tutti i file", "*.*")])
        self.add_paths(paths)

    def add_paths(self, paths):
        found, skipped = [], 0
        for p in paths:
            if os.path.isdir(p):
                for dp, _dn, fn in os.walk(p):
                    for n in sorted(fn):
                        found.append(os.path.join(dp, n))
                    if len(found) > 2000:
                        break
            else:
                found.append(p)
        known = {it["path"] for it in self.items.values()}
        added = 0
        for p in found:
            p = os.path.normpath(p)
            if p in known or not os.path.isfile(p):
                continue
            tg = engine.targets_for(p)
            if not tg:
                skipped += 1
                continue
            iid = self.tree.insert("", "end", values=("", "", "", ""))
            self.items[iid] = dict(path=p, target=engine.default_target(p), state="wait", msg="", outputs=[])
            known.add(p)
            added += 1
            self._row(iid)
        self._refresh()
        if skipped:
            self.status.set(f"{added} file aggiunti · {skipped} ignorati (formato non supportato)")
        elif added:
            self.status.set(f"{added} file aggiunti.")

    def _row(self, iid):
        it = self.items[iid]
        key = formats.key_for_path(it["path"])
        state = {"wait": "In attesa", "run": "In corso…", "ok": "✓ Fatto", "err": "✗ Errore",
                 "cancel": "Annullato"}[it["state"]]
        if it["state"] == "ok" and len(it["outputs"]) > 1:
            state = f"✓ Fatto ({len(it['outputs'])} file)"
        tags = []
        if it["state"] in ("ok", "err"):
            tags.append(it["state"])
        if self.tree.index(iid) % 2:
            tags.append("odd")
        self.tree.item(iid, values=(os.path.basename(it["path"]), formats.label(key), f'{formats.label(it["target"])}  ▾', state),
                       tags=tags)

    def remove_selected(self):
        if self.worker and self.worker.is_alive():
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.items.pop(iid, None)
        for iid in self.tree.get_children():
            self._row(iid)
        self._refresh()

    def clear(self):
        if self.worker and self.worker.is_alive():
            return
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self.progress["value"] = 0
        self.status.set("Elenco svuotato.")
        self._refresh()

    # ── scelta del formato in riga ─────────────────────────
    def _close_edit(self):
        if self.edit_box is not None:
            try:
                self.edit_box.destroy()
            except tk.TclError:
                pass
            self.edit_box = None

    def _on_click(self, event):
        self._close_edit()
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#3":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or (self.worker and self.worker.is_alive()):
            return
        self.root.after(10, lambda: self._edit_target(iid))

    def _edit_target(self, iid):
        box = self.tree.bbox(iid, "#3")
        if not box or iid not in self.items:
            return
        it = self.items[iid]
        vals = engine.targets_for(it["path"])
        var = tk.StringVar(value=it["target"])
        cb = ttk.Combobox(self.tree, state="readonly", values=vals, textvariable=var, width=8)
        cb.place(x=box[0], y=box[1], width=box[2], height=box[3])
        self.edit_box = cb

        def done(_e=None):
            it["target"] = var.get()
            it["state"], it["msg"] = "wait", ""
            self._close_edit()
            self._row(iid)
            self._refresh()
        cb.bind("<<ComboboxSelected>>", done)
        cb.bind("<Escape>", lambda e: self._close_edit())
        cb.focus_set()
        self.root.after(30, lambda: cb.event_generate("<Down>") if self.edit_box is cb else None)

    def _on_double(self, event):
        iid = self.tree.identify_row(event.y)
        it = self.items.get(iid)
        if it and it["state"] == "ok" and it["outputs"]:
            open_path(os.path.dirname(it["outputs"][0]))

    def _apply_bulk(self, _e=None):
        tg = self.bulk_target.get()
        ids = self.tree.selection() or self.tree.get_children()
        for iid in ids:
            it = self.items[iid]
            if tg in engine.targets_for(it["path"]):
                it["target"], it["state"], it["msg"] = tg, "wait", ""
                self._row(iid)
        self._refresh()

    # ── pannelli ───────────────────────────────────────────
    def _refresh(self):
        has = bool(self.items)
        if has:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        ids = self.tree.selection() or self.tree.get_children()
        common = None
        for iid in ids:
            ts = set(engine.targets_for(self.items[iid]["path"]))
            common = ts if common is None else common & ts
        order = [k for k in list(formats.FORMATS) if common and k in common]
        self.bulk.configure(values=order)
        self.bulk_target.set("")
        sel = self.tree.selection()
        if len(sel) >= 1 and sel[0] in self.items:
            it = self.items[sel[0]]
            key = formats.key_for_path(it["path"])
            self.info_src.configure(text=f"Da {formats.label(key)} — {formats.blurb(key)}")
            self.info_dst.configure(text=f"A {formats.label(it['target'])} — {formats.blurb(it['target'])}")
            if it["state"] == "err" and it["msg"]:
                self.info_dst.configure(text=f"✗ {it['msg']}")
        else:
            self.info_src.configure(text="Seleziona un file per leggere cos'è il suo formato e un po' della sua storia.")
            self.info_dst.configure(text="")
        busy = bool(self.worker and self.worker.is_alive())
        self.go_btn.configure(state="disabled" if (not has and not busy) else "normal",
                              text="Annulla" if busy else "Converti")
        self.open_btn.configure(state="normal" if self.last_dir and not busy else "disabled")

    def _dest_toggle(self):
        st = "normal" if self.dest_mode.get() == "custom" else "disabled"
        self.dest_entry.configure(state=st)
        self.dest_btn.configure(state=st)

    def pick_dest(self):
        d = filedialog.askdirectory(title="Cartella di destinazione", initialdir=self.dest_dir.get() or None)
        if d:
            self.dest_dir.set(os.path.normpath(d))

    def open_output(self):
        if self.last_dir:
            open_path(self.last_dir)

    # ── conversione ────────────────────────────────────────
    def start(self):
        if self.worker and self.worker.is_alive():
            self.cancel.set()
            self.status.set("Annullamento in corso…")
            return
        if not self.items:
            return
        if self.dest_mode.get() == "custom":
            d = self.dest_dir.get().strip()
            if not d:
                messagebox.showwarning(APP_NAME, "Scegli una cartella di destinazione.")
                return
        opts = Options(quality=int(self.quality.get()), strip_metadata=self.strip.get(),
                       overwrite=self.overwrite.get(),
                       csv_sep="," if self.csv_sep.get().startswith("Virgola") else ";")
        jobs = []
        for iid in self.tree.get_children():
            it = self.items[iid]
            out_dir = self.dest_dir.get().strip() if self.dest_mode.get() == "custom" else os.path.dirname(it["path"])
            jobs.append((iid, it["path"], it["target"], out_dir))
            it["state"], it["msg"], it["outputs"] = "wait", "", []
            self._row(iid)
        self.cancel.clear()
        self.progress.configure(maximum=len(jobs), value=0)
        self.n_ok = self.n_err = 0
        self.status.set("Conversione in corso…")
        self.worker = threading.Thread(target=self._work, args=(jobs, opts), daemon=True)
        self.worker.start()
        self._refresh()

    def _work(self, jobs, opts):
        for iid, path, target, out_dir in jobs:
            if self.cancel.is_set():
                self.q.put(("cancel", iid))
                continue
            self.q.put(("run", iid))
            try:
                out = engine.convert(path, target, out_dir, opts, self.cancel)
                self.q.put(("ok", iid, out))
            except Cancelled:
                self.q.put(("cancel", iid))
            except ConversionError as exc:
                self.q.put(("err", iid, str(exc)))
            except Exception as exc:  # non dovrebbe accadere
                self.q.put(("err", iid, f"{type(exc).__name__}: {exc}"))
        self.q.put(("end",))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "end":
                    self._finish()
                    continue
                iid = msg[1]
                it = self.items.get(iid)
                if not it:
                    continue
                if kind == "run":
                    it["state"] = "run"
                elif kind == "ok":
                    it["state"], it["outputs"] = "ok", msg[2]
                    self.n_ok += 1
                    self.last_dir = os.path.dirname(msg[2][0])
                    self.progress["value"] = self.progress["value"] + 1
                elif kind == "err":
                    it["state"], it["msg"] = "err", msg[2]
                    self.n_err += 1
                    self.progress["value"] = self.progress["value"] + 1
                elif kind == "cancel":
                    it["state"] = "cancel"
                self._row(iid)
                if kind in ("ok", "err"):
                    self.status.set(f"{self.n_ok} completati · {self.n_err} con errori")
                if iid in self.tree.selection():
                    self._refresh_info_only()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _refresh_info_only(self):
        sel = self.tree.selection()
        if sel and sel[0] in self.items and self.items[sel[0]]["state"] == "err":
            self.info_dst.configure(text=f"✗ {self.items[sel[0]]['msg']}")

    def _finish(self):
        if self.cancel.is_set():
            self.status.set(f"Annullato · {self.n_ok} completati")
        elif self.n_err:
            self.status.set(f"Finito: {self.n_ok} completati, {self.n_err} con errori — selezionali per leggere il motivo")
        else:
            self.status.set(f"Finito: {self.n_ok} file convertiti.")
        self._refresh()

    # ── finestra "Formati supportati" ──────────────────────
    def show_formats(self):
        win = tk.Toplevel(self.root)
        win.title("Formati supportati")
        win.geometry(f"{int(760 * self.scale)}x{int(600 * self.scale)}")
        win.configure(bg=C["bg"])
        txt = tk.Text(win, wrap="word", bg="white", fg=C["text"], relief="flat", padx=16, pady=12,
                      font=(self.family, 10), spacing3=6, borderwidth=0, highlightthickness=0)
        sb = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        txt.tag_configure("kind", font=(self.family, 13, "bold"), foreground=C["accent"], spacing1=12, spacing3=6)
        txt.tag_configure("name", font=(self.family, 10, "bold"))
        txt.tag_configure("meta", foreground=C["muted"], font=(self.family, 9))
        for kind, kname in formats.KINDS.items():
            txt.insert("end", kname + "\n", "kind")
            for f in formats.FORMATS.values():
                if f.kind != kind:
                    continue
                r, w = engine.can_read(f.key), engine.can_write(f.key)
                mode = "lettura e scrittura" if (r and w) else "solo lettura" if r else "non disponibile su questo computer"
                txt.insert("end", f.label, "name")
                txt.insert("end", f"  {' '.join(f.exts)} · {mode}\n", "meta")
                txt.insert("end", f.blurb + "\n")
        txt.configure(state="disabled")


def run():
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    App(root)
    root.mainloop()
