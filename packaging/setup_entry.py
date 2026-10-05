"""AuxySecurity kurulum programi (AuxySecurity-Setup.exe).

Pencereli kurulum:  AuxySecurity-Setup.exe
Sessiz kurulum   :  AuxySecurity-Setup.exe /S [/DIR=C:\\Program Files\\AuxySecurity] [/AUTOSTART] [/CONTEXTMENU] [/DESKTOP] [/NOSTARTMENU] [/NOGDPI] [/NOWARP]
Gelistirme       :  python packaging/setup_entry.py --payload <payload.zip> [--dir <hedef>] [/S ...]

Yonetici yetkisi gerekir (Program Files). Uygulama dosyalari kurulum programina gomulu payload.zip'ten cikarilir.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path

# gelistirmede src'yi bul; paketlenmiste modüller zaten gomulu
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auxy import __version__  # noqa: E402
from auxy.core import install, system  # noqa: E402


def parse(argv: list[str]) -> dict:
    opts = {"silent": False, "dir": None, "autostart": False, "context": False, "desktop": False,
            "start_menu": True, "payload": None, "gdpi": True, "warp": True}
    it = iter(argv)
    for a in it:
        low = a.lower()
        if low in ("/s", "--silent"):
            opts["silent"] = True
        elif low.startswith("/dir="):
            opts["dir"] = a[5:].strip('"')
        elif low == "--dir":
            opts["dir"] = next(it, None)
        elif low in ("/autostart", "--autostart"):
            opts["autostart"] = True
        elif low in ("/contextmenu", "--context-menu"):
            opts["context"] = True
        elif low in ("/desktop", "--desktop"):
            opts["desktop"] = True
        elif low in ("/nostartmenu", "--no-start-menu"):
            opts["start_menu"] = False
        elif low in ("/nogdpi", "--no-gdpi"):
            opts["gdpi"] = False
        elif low in ("/nowarp", "--no-warp"):
            opts["warp"] = False
        elif low == "--payload":
            opts["payload"] = next(it, None)
    return opts


def payload_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / "payload.zip"


def build_options(o: dict) -> install.InstallOptions:
    io = install.InstallOptions(start_menu=o["start_menu"], desktop=o["desktop"], autostart=o["autostart"],
                                context_menu=o["context"], gdpi=o["gdpi"], warp=o["warp"])
    if o["dir"]:
        io.dest = Path(o["dir"])
    return io


def message_box(text: str, flags: int = 0x40) -> None:
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, text, f"AuxySecurity {__version__} Kurulumu", flags)


def launch_unelevated(exe: Path) -> None:
    """Kurulum yonetici yetkisiyle calisir; uygulamayi YUKSELTILMEMIS kullanici olarak acmak icin explorer araciligi."""
    subprocess.Popen(["explorer.exe", str(exe)])


def run_silent(o: dict) -> int:
    try:
        steps = install.install(payload_path(o["payload"]), build_options(o), log=lambda m: None)
    except Exception as exc:  # noqa: BLE001
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    print("\n".join(steps))
    return 0


def run_gui(o: dict) -> int:
    import tkinter as tk
    from tkinter import filedialog, ttk

    opts = build_options(o)
    root = tk.Tk()
    root.title(f"AuxySecurity {__version__} Kurulumu")
    root.geometry("560x540")
    root.resizable(False, False)
    pad = {"padx": 18}

    ttk.Label(root, text="AuxySecurity", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(16, 0), **pad)
    ttk.Label(root, text="Windows Güvenlik (Defender) kontrol paneli. Kurulum yönetici izni gerektirir; "
                         "ayarların ve karantina kasan korunur.", wraplength=520, foreground="#555").pack(anchor="w", **pad)

    ttk.Label(root, text="Kurulum klasörü").pack(anchor="w", pady=(14, 2), **pad)
    row = ttk.Frame(root)
    row.pack(fill="x", **pad)
    path_var = tk.StringVar(value=str(opts.dest))
    ttk.Entry(row, textvariable=path_var).pack(side="left", fill="x", expand=True)
    ttk.Button(row, text="Gözat…", command=lambda: path_var.set(
        filedialog.askdirectory(initialdir=path_var.get()) or path_var.get())).pack(side="left", padx=(6, 0))

    vars_ = {k: tk.BooleanVar(value=v) for k, v in (("start_menu", opts.start_menu), ("desktop", opts.desktop),
                                                    ("autostart", opts.autostart), ("context", opts.context_menu),
                                                    ("gdpi", opts.gdpi), ("warp", opts.warp))}
    for key, label in (("start_menu", "Başlat menüsü kısayolları"), ("desktop", "Masaüstü kısayolu"),
                       ("autostart", "Windows açılışında tray ajanını başlat (yüksek yetkili görev)"),
                       ("context", "Sağ tık menüsüne 'Auxy ile tara' ekle"),
                       ("gdpi", "GoodbyeDPI hizmetini kaydet (uygulamayla birlikte gelir; mevcut hizmetin ayarları korunur)"),
                       ("warp", "Cloudflare WARP kurulu değilse arka planda kur (internet gerekir)")):
        ttk.Checkbutton(root, text=label, variable=vars_[key]).pack(anchor="w", pady=2, **pad)

    log = tk.Text(root, height=7, state="disabled", font=("Consolas", 9), background="#f6f6f6")
    log.pack(fill="x", pady=(12, 6), **pad)
    bar = ttk.Progressbar(root, mode="indeterminate")
    bar.pack(fill="x", **pad)
    buttons = ttk.Frame(root)
    buttons.pack(fill="x", pady=12, **pad)
    q: queue.Queue = queue.Queue()
    state = {"dest": None}

    def say(text: str) -> None:
        log.configure(state="normal")
        log.insert("end", text + "\n")
        log.see("end")
        log.configure(state="disabled")

    def work() -> None:
        try:
            o2 = dict(o, dir=path_var.get(), start_menu=vars_["start_menu"].get(), desktop=vars_["desktop"].get(),
                      autostart=vars_["autostart"].get(), context=vars_["context"].get(),
                      gdpi=vars_["gdpi"].get(), warp=vars_["warp"].get())
            io = build_options(o2)
            state["dest"] = io.dest
            steps = install.install(payload_path(o["payload"]), io, log=lambda m: q.put(("log", m)))
            q.put(("done", steps))
        except Exception as exc:  # noqa: BLE001
            q.put(("error", str(exc)))

    def poll() -> None:
        try:
            while True:
                kind, data = q.get_nowait()
                if kind == "log":
                    say(data)
                elif kind == "done":
                    bar.stop()
                    say("\n✔ Kurulum tamamlandı:\n" + "\n".join(f"  • {s}" for s in data))
                    start_btn.configure(state="normal")
                    close_btn.configure(state="normal")
                    return
                else:
                    bar.stop()
                    say(f"\n✘ Kurulum başarısız: {data}")
                    install_btn.configure(state="normal")
                    close_btn.configure(state="normal")
                    return
        except queue.Empty:
            pass
        root.after(100, poll)

    def start_install() -> None:
        install_btn.configure(state="disabled")
        close_btn.configure(state="disabled")
        bar.start(12)
        threading.Thread(target=work, daemon=True).start()
        poll()

    install_btn = ttk.Button(buttons, text="Kur", command=start_install)
    install_btn.pack(side="left")
    start_btn = ttk.Button(buttons, text="AuxySecurity'yi başlat", state="disabled",
                           command=lambda: (launch_unelevated(state["dest"] / system.GUI_EXE), root.destroy()))
    start_btn.pack(side="left", padx=8)
    close_btn = ttk.Button(buttons, text="Kapat", command=root.destroy)
    close_btn.pack(side="right")
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    o = parse(sys.argv[1:] if argv is None else argv)
    if not system.is_admin():
        # PyInstaller --uac-admin zaten yukseltir; gelistirmede (python ile) kendimizi yukselt
        if getattr(sys, "frozen", False):
            message_box("Kurulum için yönetici izni gerekir.", 0x10)
            return 3
        import ctypes
        import subprocess as sp

        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, sp.list2cmdline(
            [str(Path(__file__).resolve()), *sys.argv[1:]]), None, 1)
        return 0 if rc > 32 else 3
    return run_silent(o) if o["silent"] else run_gui(o)


if __name__ == "__main__":
    raise SystemExit(main())
