"""Ag guvenligi sayfasi: guvenlik duvari (profiller + kurallar), GoodbyeDPI ve Cloudflare WARP."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from auxy.core import actions, firewall, netservices, winsec
from auxy.gui.security_page import BAD, CONFIRM_OFF, GOOD, MUTED
from auxy.gui.widgets import Card, page_header
from auxy.gui import theme

ORANGE = theme.WARN
INBOUND_TR = {"Varsayılan": "default", "Engelle": "block", "İzin ver": "allow"}
INBOUND_BACK = {v: k for k, v in INBOUND_TR.items()}
RULES_SHOWN = 40
FW_KEYS = ("fw_domain", "fw_private", "fw_public")
FW_IN_KEYS = ("fw_in_domain", "fw_in_private", "fw_in_public")

GDPI_STATE_TR = {"running": ("● Çalışıyor", GOOD), "stopped": ("● Durduruldu", BAD),
                 "start_pending": ("◌ Başlıyor…", ORANGE), "stop_pending": ("◌ Duruyor…", ORANGE),
                 "paused": ("● Duraklatıldı", ORANGE), "unknown": ("● Bilinmiyor", ORANGE)}
WARP_STATUS_TR = {"Connected": ("● Bağlı", GOOD), "Disconnected": ("● Bağlı değil", BAD),
                  "Connecting": ("◌ Bağlanıyor…", ORANGE), "Unable": ("● Bağlanamıyor", BAD)}
WARP_MODE_BACK = {v: k for k, v in netservices.WARP_MODES.items()}
WARP_PROTO_BACK = {v: k for k, v in netservices.WARP_PROTOCOLS.items()}
WARP_POLL_MS, WARP_POLL_MAX = 1500, 20  # ~30 sn


class NetworkPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = page_header(self, "Ağ güvenliği", "İnternet bağlantını koruyan ve engelleri aşan araçlar.")
        ctk.CTkButton(head.actions, text="Yenile", width=80, command=self.refresh).pack(side="right")
        self.message = head.message
        self.message.pack(side="right", padx=(0, 12))  # butonlarin soluna

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        # ---- GoodbyeDPI
        c = Card(body, "GoodbyeDPI", 0, "Operatör kaynaklı erişim engellerini aşmaya yardımcı olan arka plan hizmeti.")
        row = c.button_bar(pady=(0, 4))
        self.gdpi_state = ctk.CTkLabel(row, text="Okunuyor…", font=ctk.CTkFont(size=18, weight="bold"))
        self.gdpi_state.pack(side="left")
        self.gdpi_stop_btn = ctk.CTkButton(row, text="Kapat", width=90, height=34, fg_color=theme.BTN_BAD,
                                           hover_color=theme.BTN_BAD_HOVER,
                                           command=lambda: self.gdpi_op("gdpi-stop"))
        self.gdpi_stop_btn.pack(side="right")
        self.gdpi_start_btn = ctk.CTkButton(row, text="Başlat", width=90, height=34,
                                            command=lambda: self.gdpi_op("gdpi-start"))
        self.gdpi_start_btn.pack(side="right", padx=(0, 8))
        self.gdpi_auto = c.switch_row("Windows ile otomatik başlasın", self._toggle_gdpi_auto,
                                      "Bilgisayar açıldığında hizmet kendiliğinden çalışır.")
        self.gdpi_warn = c.line("", theme.WARN)
        self.gdpi_fix_btn = ctk.CTkButton(c, text="Güvenli konuma taşı / kur", width=190, height=30,
                                          command=lambda: self.gdpi_op("gdpi-install"))
        self.gdpi_fix_btn.grid(row=c.next_row, column=0, sticky="w", padx=18, pady=(0, 10))
        c.next_row += 1
        self.gdpi_fix_btn.grid_remove()
        det = c.collapsible("Ayrıntılar")
        self.gdpi_detail = ctk.CTkLabel(det.body, text="", anchor="w", justify="left", text_color=MUTED,
                                        wraplength=560)
        self.gdpi_detail.grid(row=0, column=0, sticky="w", padx=12, pady=(2, 8))

        # ---- WARP
        c = Card(body, "Cloudflare WARP", 1, "Bağlantını Cloudflare üzerinden şifreler ve DNS'i korur.")
        row = c.button_bar(pady=(0, 4))
        self.warp_state = ctk.CTkLabel(row, text="Okunuyor…", font=ctk.CTkFont(size=18, weight="bold"))
        self.warp_state.pack(side="left")
        self.warp_off_btn = ctk.CTkButton(row, text="Bağlantıyı kes", width=120, height=34, fg_color=theme.BTN_BAD,
                                          hover_color=theme.BTN_BAD_HOVER,
                                          command=lambda: self.warp_op("warp-disconnect"))
        self.warp_off_btn.pack(side="right")
        self.warp_on_btn = ctk.CTkButton(row, text="Bağlan", width=90, height=34,
                                         command=lambda: self.warp_op("warp-connect"))
        self.warp_on_btn.pack(side="right", padx=(0, 8))
        self.warp_install_btn = ctk.CTkButton(row, text="WARP'ı kur", width=110, height=34, command=self.install_warp)
        self.warp_install_btn.pack(side="right")
        self.warp_install_btn.pack_forget()  # kurulu degilse okuma sonrasi gosterilir
        self.warp_detail = c.line("", MUTED)
        self.proto_menu = c.menu_row("Bağlantı protokolü", list(WARP_PROTO_BACK), self._set_protocol,
                                     "MASQUE yeni ve hızlıdır; WireGuard eski ama yaygın uyumludur.", 240)
        self.mode_menu = c.menu_row("Çalışma kipi", list(WARP_MODE_BACK), self._set_mode,
                                    "Tüm trafiği mi yoksa yalnızca DNS'i mi koruyacağını seçer.", 240)

        # ---- Guvenlik duvari
        c = Card(body, "Güvenlik duvarı", 2, "Bilgisayarına ağdan gelen bağlantıları denetler.")
        self.sw: dict[str, ctk.CTkSwitch] = {}
        names = {"fw_domain": ("Etki alanı ağı", "Kurum/okul ağları."), "fw_private": ("Özel ağ", "Ev ve iş yerindeki güvendiğin ağlar."),
                 "fw_public": ("Genel ağ", "Kafe, otel, havalimanı gibi herkese açık ağlar.")}
        for key in FW_KEYS:
            self.sw[key] = c.switch_row(names[key][0], lambda k=key: self._toggle(k), names[key][1])
        c.line("Gelen bağlantılar için varsayılan eylem ('İzin ver' güvenliği azaltır):", MUTED)
        self.inbound_menus: dict[str, ctk.CTkOptionMenu] = {}
        for key in FW_IN_KEYS:
            self.inbound_menus[key] = c.menu_row(winsec.WINSEC_SETTINGS[key].label.split(": ")[1], list(INBOUND_TR),
                                                 lambda shown, k=key: self._set_inbound(k, shown), "", 130)

        # ---- Guvenlik duvari kurallari (gelismis)
        c = Card(body, "Güvenlik duvarı kuralları", 3, "Hangi programların ağa erişebileceğini yönet.")
        bar = c.button_bar(pady=(0, 6))
        ctk.CTkButton(bar, text="Programı engelle…", width=150, command=self.block_program).pack(side="left")
        ctk.CTkButton(bar, text="Kuralları listele", width=130, command=self.load_rules).pack(side="left", padx=8)
        adv = c.collapsible("Kural listesi")
        fbar = ctk.CTkFrame(adv.body, fg_color="transparent")
        fbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(2, 4))
        self.rule_filter = ctk.CTkEntry(fbar, width=240, placeholder_text="Ara (ad / program)")
        self.rule_filter.pack(side="left")
        self.rule_filter.bind("<KeyRelease>", lambda _e: self._render_rules())
        self.rules_note = ctk.CTkLabel(adv.body, text="('Kuralları listele'ye bas.)", text_color=MUTED, anchor="w",
                                       justify="left", wraplength=560)
        self.rules_note.grid(row=1, column=0, sticky="w", padx=12, pady=2)
        self.rules_frame = ctk.CTkFrame(adv.body, fg_color="transparent")
        self.rules_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        self.rules_frame.columnconfigure(0, weight=1)
        self._rules_section = adv
        self.rules_cache: list[dict] = []
        self.blocks_cache: list[dict] = []
        self.gdpi: netservices.ServiceInfo | None = None
        self.warp: netservices.WarpInfo | None = None
        self._poll_token: object | None = None
    # ---- mesaj ----
    def say(self, text: str, error: bool = False) -> None:
        self.message.configure(text=text, text_color=BAD if error else theme.TEXT)

    # ---- veri ----
    def refresh(self) -> None:
        self.app.worker.submit(lambda: (netservices.read_service(), netservices.bundled_tools_dir()), self._show_gdpi)
        self.app.worker.submit(netservices.read_warp, self._show_warp)
        self.app.worker.submit(lambda: winsec.WinSecService().get_many(FW_KEYS + FW_IN_KEYS), self._show_firewall)

    def _show_firewall(self, res, exc) -> None:
        if exc is not None:
            self.say(f"Okunamadı: {exc}", error=True)
            return
        for key, sw in self.sw.items():
            (sw.select if res[key] == "on" else sw.deselect)()
        for key, menu in self.inbound_menus.items():
            menu.set(INBOUND_BACK.get(res.get(key, "default"), "Varsayılan"))

    # ---- GoodbyeDPI ----
    def _show_gdpi(self, res, exc) -> None:
        if exc is not None:
            self.gdpi_state.configure(text="● Okunamadı", text_color=BAD)
            self.gdpi_detail.configure(text=str(exc))
            return
        info, bundled = res
        self.gdpi = info
        fix = False
        if not info.installed:
            self.gdpi_state.configure(text="● Kurulu değil", text_color=MUTED)
            self.gdpi_detail.configure(text="Hizmet kayıtlı değil." + (" 'Kur' ile uygulamayla gelen kopya kaydedilir." if bundled else ""))
            self.gdpi_start_btn.configure(state="disabled")
            self.gdpi_stop_btn.configure(state="disabled")
            self.gdpi_auto.configure(state="disabled")
            self.gdpi_warn.configure(text="")
            fix = bundled is not None
            self.gdpi_fix_btn.configure(text="Kur")
        else:
            text, color = GDPI_STATE_TR.get(info.state, GDPI_STATE_TR["unknown"])
            self.gdpi_state.configure(text=text, text_color=color)
            self.gdpi_detail.configure(text=f"{info.binary}\nArgümanlar: {info.arguments or '(yok)'}")
            running = info.state == "running"
            self.gdpi_start_btn.configure(state="disabled" if running else "normal")
            self.gdpi_stop_btn.configure(state="normal" if running or info.state == "start_pending" else "disabled")
            self.gdpi_auto.configure(state="normal")
            (self.gdpi_auto.select if info.start_type == "auto" else self.gdpi_auto.deselect)()
            if netservices.trusted_location(info.binary):
                self.gdpi_warn.configure(text="")
            else:
                self.gdpi_warn.configure(
                    text="⚠ Hizmet SİSTEM yetkisiyle, kullanıcının yazabildiği bir klasördeki dosyayı çalıştırıyor: "
                         "bu hesapta çalışan zararlı bir program onu değiştirip yetki kazanabilir.")
                fix = bundled is not None
                self.gdpi_fix_btn.configure(text="Güvenli konuma taşı")
        (self.gdpi_fix_btn.grid if fix else self.gdpi_fix_btn.grid_remove)()

    def gdpi_op(self, op: str) -> None:
        if op == "gdpi-stop" and not messagebox.askyesno(
                "GoodbyeDPI'i kapat", "Hizmet durdurulacak; engelli sitelere erişim eski haline dönebilir.\nDevam edilsin mi?"):
            return
        self.say("GoodbyeDPI güncelleniyor… (yönetici izni istenebilir)")
        self.app.worker.submit(lambda: actions.net_op(op), lambda r, e: self._net_done(r, e))

    def _toggle_gdpi_auto(self) -> None:
        self.gdpi_op("gdpi-auto" if self.gdpi_auto.get() else "gdpi-manual")

    # ---- WARP ----
    def _show_warp(self, res, exc, polling: bool = False) -> None:
        if exc is not None:
            self.warp_state.configure(text="● Okunamadı", text_color=BAD)
            self.warp_detail.configure(text=str(exc))
            return
        w = res
        self.warp = w
        if w.status == "Connecting" and not polling:  # sayfa baglanma sirasinda acildi: durum oturana kadar izle
            self._poll_warp("Connected")
        for b in (self.warp_on_btn, self.warp_off_btn):
            b.configure(state="normal" if w.installed else "disabled")
        if w.installed:
            self.warp_install_btn.pack_forget()
        else:
            self.warp_install_btn.pack(side="right")
        self.proto_menu.configure(state="normal" if w.installed else "disabled")
        self.mode_menu.configure(state="normal" if w.installed else "disabled")
        if not w.installed:
            self.warp_state.configure(text="● Kurulu değil", text_color=MUTED)
            self.warp_detail.configure(text="Cloudflare WARP bulunamadı. 'WARP'ı kur' resmi paketi arka planda kurar (internet gerekir).")
            return
        active = w.status in ("Connected", "Connecting")
        self.warp_on_btn.configure(state="disabled" if active else "normal")
        self.warp_off_btn.configure(state="normal" if active else "disabled")
        text, color = WARP_STATUS_TR.get(w.status, (f"● {w.status}", ORANGE))
        self.warp_state.configure(text=text, text_color=color)
        svc = {True: "çalışıyor", False: "DURDURULMUŞ", None: "?"}[w.service_running]
        self.warp_detail.configure(text=f"Hizmet: {svc}" + (f"  •  {w.reason}" if w.reason else "")
                                   + (f"\n{w.error}" if w.error else ""))
        if w.protocol in netservices.WARP_PROTOCOLS:
            self.proto_menu.set(netservices.WARP_PROTOCOLS[w.protocol])
        if w.mode in netservices.WARP_MODES:
            self.mode_menu.set(netservices.WARP_MODES[w.mode])

    def warp_op(self, op: str, value: str = "") -> None:
        self.say("WARP güncelleniyor…")
        expect = {"warp-connect": "Connected", "warp-disconnect": "Disconnected"}.get(op)

        def done(res, exc):
            self._net_done(res, exc)
            if expect and exc is None and res.ok:
                self._poll_warp(expect)  # baglanma/kesilme birkac saniye surer: durum oturana kadar izle

        self.app.worker.submit(lambda: actions.net_op(op, value), done)

    def _poll_warp(self, expect: str, left: int = WARP_POLL_MAX) -> None:
        """Durum `expect` olana (ya da sure dolana) kadar WARP'i kisa araliklarla okur."""
        self._poll_token = token = object()  # yeni bir izleme eskisini iptal eder

        def tick():
            if self._poll_token is not token:
                return

            def got(res, exc):
                if self._poll_token is not token:
                    return
                self._show_warp(res, exc, polling=True)
                if exc is None and res.status == expect:
                    self.say("WARP bağlı." if expect == "Connected" else "WARP bağlantısı kesildi.")
                elif left > 0 and exc is None:
                    self._poll_warp(expect, left - 1)
                else:
                    self.say(f"WARP hâlâ '{WARP_STATUS_TR.get(res.status, (res.status,))[0].lstrip('●◌ ')}' durumunda.",
                             error=True)

            self.app.worker.submit(netservices.read_warp, got)

        self.after(WARP_POLL_MS, tick)

    def _set_protocol(self, shown: str) -> None:
        proto = WARP_PROTO_BACK[shown]
        if self.warp is not None and proto == self.warp.protocol:
            return
        if not messagebox.askyesno("Protokolü değiştir", f"WARP tüneli {proto} protokolüne geçecek; bağlantı kısa süre kopabilir.\nDevam edilsin mi?"):
            self.refresh()
            return
        self.warp_op("warp-protocol", proto)

    def _set_mode(self, shown: str) -> None:
        mode = WARP_MODE_BACK[shown]
        if self.warp is not None and mode == self.warp.mode:
            return
        if not messagebox.askyesno("Kipi değiştir", f"WARP '{shown}' kipine geçecek.\nDevam edilsin mi?"):
            self.refresh()
            return
        self.warp_op("warp-mode", mode)

    def install_warp(self) -> None:
        if not messagebox.askyesno("WARP'ı kur", "Cloudflare WARP resmi paketi (winget) ile kurulacak. İnternet gerekir; "
                                                  "Windows yönetici izni isteyebilir.\nDevam edilsin mi?"):
            return
        self.say("WARP kuruluyor… (birkaç dakika sürebilir)")
        self.warp_install_btn.configure(state="disabled")

        def done(res, exc):
            self.warp_install_btn.configure(state="normal")
            self._net_done(res, exc)

        self.app.worker.submit(lambda: _as_action(netservices.install_warp()), done)

    def _net_done(self, res, exc) -> None:
        if exc is not None:
            self.say(str(exc), error=True)
        else:
            self.say(res.message, error=not res.ok)
        self.refresh()

    # ---- guvenlik duvari ----
    def _toggle(self, key: str) -> None:
        sw = self.sw[key]
        value = "on" if sw.get() else "off"
        if value == "off" and key in CONFIRM_OFF and not messagebox.askyesno(
                "Emin misin?", CONFIRM_OFF[key] + "\nDevam edilsin mi?", icon="warning"):
            sw.select()
            return
        self._apply(key, value)

    def _set_inbound(self, key: str, shown: str) -> None:
        value = INBOUND_TR[shown]
        if value == "allow" and not messagebox.askyesno(
                "Emin misin?", "Gelen bağlantılara varsayılan olarak İZİN vermek bilgisayarını ağdan gelen "
                               "saldırılara açar.\nDevam edilsin mi?", icon="warning"):
            self.refresh()
            return
        self._apply(key, value)

    def _apply(self, key: str, value: str) -> None:
        label = winsec.WINSEC_SETTINGS[key].label
        self.say(f"{label}: uygulanıyor…")
        self.app.worker.submit(lambda: actions.apply_winsec(key, value),
                               lambda res, exc: self._done(label, res, exc))

    def _done(self, label: str, res, exc) -> None:
        if exc is not None:
            self.say(str(exc), error=True)
        else:
            self.say(f"{label}: {res.message}" if res.ok else res.message, error=not res.ok)
        self.refresh()

    # ---- guvenlik duvari kurallari ----
    def load_rules(self) -> None:
        self.rules_note.configure(text="Kurallar okunuyor…")

        def read():
            rules = actions.firewall_op("list")
            blocks = actions.firewall_op("list-blocks")
            return rules, blocks

        self.app.worker.submit(read, self._rules_loaded)

    def _rules_loaded(self, res, exc) -> None:
        if not self._rules_section.is_open:
            self._rules_section.toggle()  # liste istendi: bolumu ac
        if exc is not None:
            self.rules_note.configure(text=str(exc), text_color=BAD)
            return
        rules, blocks = res
        if not rules.ok:
            self.rules_note.configure(text=rules.message, text_color=BAD)
            return
        self.rules_cache = rules.data or []
        self.blocks_cache = (blocks.data or []) if blocks.ok else []
        self._render_rules()

    def _render_rules(self) -> None:
        for w in self.rules_frame.winfo_children():
            w.destroy()
        q = self.rule_filter.get().strip().lower()
        shown = [r for r in self.rules_cache
                 if not q or q in r["display_name"].lower() or q in r["program"].lower() or q in r["name"].lower()]
        self.rules_note.configure(
            text=f"{len(shown)} kural" + (f" (ilk {RULES_SHOWN} gösteriliyor)" if len(shown) > RULES_SHOWN else "")
                 + f" • {len(self.blocks_cache)} engellenen program • {len(firewall.disabled_by_us())} pasifleştirdiğin kural",
            text_color=MUTED)
        row = 0
        for b in self.blocks_cache:  # bizim engelledigimiz programlar
            if b["name"].startswith(firewall.BLOCK_PREFIX + "in-"):
                ctk.CTkLabel(self.rules_frame, text=f"⛔ ENGELLİ: {b['program']}", anchor="w", wraplength=440,
                             justify="left", text_color=BAD).grid(row=row, column=0, sticky="w", pady=2)
                ctk.CTkButton(self.rules_frame, text="Engeli kaldır", width=100, height=24,
                              command=lambda n=b["name"]: self.unblock(n)).grid(row=row, column=1, padx=(8, 0))
                row += 1
        for name in firewall.disabled_by_us():  # bizim pasiflestirdiklerimiz
            ctk.CTkLabel(self.rules_frame, text=f"⏸ Pasif (senin): {name}", anchor="w", wraplength=440,
                         justify="left").grid(row=row, column=0, sticky="w", pady=2)
            ctk.CTkButton(self.rules_frame, text="Yeniden etkinleştir", width=130, height=24,
                          command=lambda n=name: self.enable_rule(n)).grid(row=row, column=1, padx=(8, 0))
            row += 1
        for r in shown[:RULES_SHOWN]:
            prog = r["program"] if r["program"] not in ("", "Any") else "(tüm programlar)"
            ctk.CTkLabel(self.rules_frame, text=f"{r['display_name']}  [{r['profile']}]\n{prog}", anchor="w",
                         wraplength=440, justify="left").grid(row=row, column=0, sticky="w", pady=2)
            ctk.CTkButton(self.rules_frame, text="Pasifleştir", width=100, height=24,
                          command=lambda x=r: self.disable_rule(x)).grid(row=row, column=1, padx=(8, 0))
            row += 1

    def disable_rule(self, r: dict) -> None:
        if not messagebox.askyesno(
                "Kuralı pasifleştir",
                f"'{r['display_name']}' kuralı pasifleştirilecek.\nProgram: {r['program'] or 'tüm programlar'}\n\n"
                "Bu kuralın izin verdiği gelen bağlantılar engellenir; bazı özellikler (yazıcı paylaşımı, "
                "uzak masaüstü vb.) çalışmayabilir. Geri alınabilir.\nDevam edilsin mi?", icon="warning"):
            return
        self._firewall_op("disable", r["name"])

    def enable_rule(self, name: str) -> None:
        self._firewall_op("enable", name)

    def block_program(self) -> None:
        path = filedialog.askopenfilename(title="Engellenecek program", filetypes=[("Programlar", "*.exe"), ("Tümü", "*.*")])
        if not path:
            return
        if not messagebox.askyesno(
                "Programı engelle",
                f"'{Path(path).name}' için gelen VE giden tüm ağ bağlantıları engellenecek.\n{path}\n\n"
                "Program internete erişemez. Geri alınabilir ('Engeli kaldır').\nDevam edilsin mi?", icon="warning"):
            return
        self._firewall_op("block", str(Path(path)))

    def unblock(self, rule_name: str) -> None:
        self._firewall_op("unblock", rule_name)

    def _firewall_op(self, op: str, value: str) -> None:
        self.say("Güvenlik duvarı güncelleniyor… (yönetici izni istenebilir)")

        def done(res, exc):
            self.say(str(exc) if exc else res.message, error=exc is not None or not res.ok)
            self.load_rules()

        self.app.worker.submit(lambda: actions.firewall_op(op, value), done)


def _as_action(res: netservices.NetResult) -> actions.ActionResult:
    return actions.ActionResult(res.ok, res.message, res.changed)

