"""DNS ve gizlilik sayfasi: DNS secimi + hiz/guvenlik testi + sifreli DNS, gizlilik ayarlari ve Tor."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from auxy.core import actions, dns, dnsscope, netservices, privacy, system, tor
from auxy.core.service import AuxyError
from auxy.gui import theme
from auxy.gui.widgets import Card, page_header

MUTED = theme.MUTED
CUSTOM = "Özel…"
PRESET_NAMES = {p.name: k for k, p in dns.PRESETS.items()}
BRIDGE_MODES = {"Doğrudan bağlan": "", "obfs4 köprüsü": "obfs4", "snowflake köprüsü": "snowflake", "meek köprüsü": "meek"}
TOR_POLL_MS, TOR_POLL_MAX = 2000, 60  # ~2 dk


class PrivacyPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.adapters: list[dns.Adapter] = []
        self.adapter_vars: dict[int, ctk.BooleanVar] = {}
        self.bench: list[dns.BenchResult] = []
        self.scope = dnsscope.load()
        self._tor_token: object | None = None

        head = page_header(self, "DNS ve gizlilik", "Daha hızlı ve daha gizli internet: DNS seçimi, şifreli DNS ve Tor.")
        ctk.CTkButton(head.actions, text="Yenile", width=80, command=self.refresh).pack(side="right")
        self.message = head.message
        self.message.pack(side="right", padx=(0, 12))

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        # ---------------- DNS
        c = Card(body, "DNS sunucusu", 0,
                 "DNS, alan adlarını (ör. youtube.com) adrese çevirir. Yurt, kampüs ya da operatör ağlarının "
                 "varsayılan DNS'i yavaş veya müdahaleci olabilir; doğru DNS internetini belirgin hızlandırabilir.")
        self.dns_current = c.line("Ağlar okunuyor…", MUTED)
        self.adapters_frame = ctk.CTkFrame(c, fg_color="transparent")
        self.adapters_frame.grid(row=c.next_row, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 4))
        c.next_row += 1
        self.dns_warn = c.line("", theme.WARN)
        self.preset_menu = c.menu_row("DNS sağlayıcısı", [*PRESET_NAMES, CUSTOM], self._preset_changed,
                                      "Hangisini seçeceğini bilmiyorsan aşağıdaki hız testini çalıştır.", 230)
        self.custom_entry = ctk.CTkEntry(c, width=330, placeholder_text="Özel DNS: örn. 1.1.1.1, 8.8.8.8")
        self.custom_row = c.next_row
        self.custom_entry.grid(row=c.next_row, column=2, padx=(0, 18), pady=(0, 6), sticky="e")
        c.next_row += 1
        self.custom_entry.grid_remove()
        self.doh_sw = c.switch_row("Şifreli DNS (DoH)", self._doh_changed,
                                   "DNS sorgularını HTTPS ile şifreler: ağ yöneticisi/operatör hangi siteleri "
                                   "çözdüğünü göremez ve sorguları değiştiremez.")
        self.strict_sw = c.switch_row("Sıkı mod", None,
                                      "Şifreli bağlantı kurulamazsa şifresiz DNS'e DÜŞME (gizlilik ↑, ağ engelliyorsa "
                                      "internet gidebilir).")
        self.strict_sw.configure(state="disabled")
        self.scope_sw = c.switch_row("Yalnızca güvendiğim ağlarda", self._scope_toggled,
                                     "Seçtiğin DNS yalnızca listedeki ağlarda (ör. evdeki Wi-Fi) kullanılır. Kampüs, "
                                     "yurt, kafe gibi diğer ağlarda DNS otomatik kalır; giriş sayfası açılır. "
                                     "Ağ değişince AuxySecurity ajanı bunu kendisi yapar.")
        self.scope_lbl = c.line("", MUTED)
        sbar = c.button_bar(pady=(0, 6))
        self.scope_add_btn = ctk.CTkButton(sbar, text="Şu anki ağı güvenilenlere ekle", width=210, height=30,
                                           fg_color="transparent", border_width=1, text_color=theme.TEXT,
                                           hover_color=theme.SURFACE_ALT, command=self.scope_add_current)
        self.scope_add_btn.pack(side="left")
        self.scope_rm_btn = ctk.CTkButton(sbar, text="Şu anki ağı listeden çıkar", width=190, height=30,
                                          fg_color="transparent", border_width=1, text_color=theme.TEXT,
                                          hover_color=theme.SURFACE_ALT, command=self.scope_remove_current)
        self.scope_rm_btn.pack(side="left", padx=8)
        self._show_scope()
        bar = c.button_bar()
        self.apply_btn = ctk.CTkButton(bar, text="Uygula (yönetici)", width=150, height=34, command=self.apply_dns)
        self.apply_btn.pack(side="left")
        ctk.CTkButton(bar, text="Eski haline döndür", width=150, height=34, fg_color="transparent", border_width=1,
                      text_color=theme.TEXT, hover_color=theme.SURFACE_ALT, command=self.reset_dns).pack(
            side="left", padx=8)
        ctk.CTkButton(bar, text="Önbelleği temizle", width=150, height=34, fg_color="transparent", border_width=1,
                      text_color=theme.TEXT, hover_color=theme.SURFACE_ALT, command=self.flush_dns).pack(side="left")

        # ---------------- hiz / guvenlik testi
        c = Card(body, "Hız ve güvenlik testi", 1,
                 "Her DNS'e gerçek sorgu gönderilir. Tahmin yok: kendi ağında hangisinin en hızlı ve güvenilir "
                 "olduğunu görürsün.")
        bar = c.button_bar(pady=(0, 6))
        self.bench_btn = ctk.CTkButton(bar, text="Testi başlat", width=130, height=34, command=self.run_bench)
        self.bench_btn.pack(side="left")
        self.use_best_btn = ctk.CTkButton(bar, text="En iyisini seç", width=130, height=34, state="disabled",
                                          command=self.use_best)
        self.use_best_btn.pack(side="left", padx=8)
        self.bench_note = c.line("(Test ~5 sn sürer; internete DNS sorgusu gönderir.)", MUTED)
        self.bench_frame = ctk.CTkFrame(c, fg_color="transparent")
        self.bench_frame.grid(row=c.next_row, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 6))
        self.bench_frame.columnconfigure(0, weight=1)
        c.next_row += 1
        info = c.collapsible("Bilgi: neden bazı DNS'ler yurtta çalışmaz?")
        ctk.CTkLabel(info.body, anchor="w", justify="left", wraplength=560, text_color=MUTED,
                     text="• 'ODTÜ DNS' gibi kurum DNS'leri yalnızca kendi ağlarından gelen sorguya yanıt verir "
                          "(ODTÜ: 144.122.0.0/16); dışarıdan, örneğin KYK yurdundan kullanılamaz.\n"
                          "• Bazı ağlar 53. portu (UDP) engeller ya da kendi sunucusuna yönlendirir. Testte "
                          "'443 kapalı' / 'sahte yanıt' görürsen o DNS bu ağda sorunludur.\n"
                          "• Şifreli DNS (DoH) 443. porttan gider; 53 engelli ağlarda çözüm olabilir.\n"
                          "• GoodbyeDPI '--dns-addr' ile DNS'i kendi sunucusuna yönlendiriyorsa sistem DNS ayarı "
                          "etkisiz kalır.").grid(row=0, column=0, sticky="w", padx=12, pady=(2, 8))

        # ---------------- gizlilik
        c = Card(body, "Gizlilik", 2, "Windows ve ağ düzeyinde seni takip etmeyi zorlaştıran ayarlar.")
        self.privacy_sw: dict[str, ctk.CTkSwitch] = {}
        for key, (_p, _n, label, hint) in privacy.FLAGS.items():
            self.privacy_sw[key] = c.switch_row(label, lambda k=key: self._toggle_flag(k), hint)
        self.mac_frame = ctk.CTkFrame(c, fg_color="transparent")
        self.mac_frame.grid(row=c.next_row, column=0, columnspan=3, sticky="ew", pady=0)
        self.mac_frame.columnconfigure(0, weight=1)
        c.next_row += 1
        self.mac_switches: dict[str, ctk.CTkSwitch] = {}
        bar = c.button_bar()
        self.trace_btn = ctk.CTkButton(bar, text="Ağ bilgimi göster", width=150, height=34, command=self.show_trace)
        self.trace_btn.pack(side="left")
        self.trace_lbl = ctk.CTkLabel(bar, text="", anchor="w", justify="left", wraplength=420, text_color=MUTED)
        self.trace_lbl.pack(side="left", padx=10)

        # ---------------- Tor
        c = Card(body, "Tor (SOCKS5 vekili)", 3,
                 "Trafiğini Tor ağı üzerinden geçirir. Bu bir VPN DEĞİLDİR: yalnızca vekil kullanan uygulamalar "
                 "(tarayıcı, curl, nmap -sT …) Tor'dan çıkar. En iyi anonimlik için Tor Browser kullan.")
        row = c.button_bar(pady=(0, 4))
        self.tor_state = ctk.CTkLabel(row, text="Okunuyor…", font=ctk.CTkFont(size=18, weight="bold"))
        self.tor_state.pack(side="left")
        self.tor_stop_btn = ctk.CTkButton(row, text="Durdur", width=90, height=34, fg_color=theme.BTN_BAD,
                                          hover_color=theme.BTN_BAD_HOVER, command=self.tor_stop)
        self.tor_stop_btn.pack(side="right")
        self.tor_start_btn = ctk.CTkButton(row, text="Başlat", width=90, height=34, command=self.tor_start)
        self.tor_start_btn.pack(side="right", padx=(0, 8))
        self.tor_install_btn = ctk.CTkButton(row, text="Tor'u kur (~21 MB)", width=150, height=34, command=self.tor_install)
        self.tor_install_btn.pack(side="right", padx=(0, 8))
        self.tor_detail = c.line("", MUTED)
        self.bridge_menu = c.menu_row("Bağlantı yöntemi", list(BRIDGE_MODES), None,
                                      "Tor engelli bir ağdaysan (ör. bazı yurt/operatör ağları) köprü seç.", 200)
        self.proxy_sw = c.switch_row("Windows vekilini Tor'a ayarla", self._toggle_proxy,
                                     "Tarayıcılar ve vekil ayarına uyan uygulamalar Tor'u kullanır. Kapatınca ya da "
                                     "Tor durunca eski ayara döner.")
        bar = c.button_bar()
        self.newnym_btn = ctk.CTkButton(bar, text="Yeni kimlik", width=120, height=34, command=self.tor_newnym)
        self.newnym_btn.pack(side="left")
        self.verify_btn = ctk.CTkButton(bar, text="Tor'u doğrula", width=130, height=34, command=self.tor_verify)
        self.verify_btn.pack(side="left", padx=8)
        self.tor_verify_lbl = ctk.CTkLabel(bar, text="", anchor="w", justify="left", wraplength=380, text_color=MUTED)
        self.tor_verify_lbl.pack(side="left", padx=6)
        self.tor_status: tor.TorStatus | None = None

    # ---- ortak ----
    def say(self, text: str, error: bool = False) -> None:
        self.message.configure(text=text, text_color=theme.BAD if error else theme.TEXT)

    def refresh(self) -> None:
        self.app.worker.submit(lambda: (dns.read_adapters(), netservices.read_service()), self._show_dns)
        self.app.worker.submit(self._read_privacy, self._show_privacy)
        self.app.worker.submit(tor.status, self._show_tor)

    # ---------------- DNS
    def _show_dns(self, res, exc) -> None:
        if exc is not None:
            self.dns_current.configure(text=f"Ağlar okunamadı: {exc}", text_color=theme.BAD)
            return
        adapters, gdpi = res
        self.adapters = adapters
        for w in self.adapters_frame.winfo_children():
            w.destroy()
        old = {i: v.get() for i, v in self.adapter_vars.items()}
        self.adapter_vars = {}
        if not adapters:
            self.dns_current.configure(text="Bağlı fiziksel ağ yok (Wi-Fi/Ethernet bağlan).", text_color=theme.WARN)
        else:
            self.dns_current.configure(text="Ayarın uygulanacağı ağlar:", text_color=MUTED)
        for i, a in enumerate(adapters):
            var = ctk.BooleanVar(value=old.get(a.index, True))
            self.adapter_vars[a.index] = var
            net = f" ({a.network}{', güvenilen' if self.scope.trusts(a.network) else ''})" if a.network else ""
            ctk.CTkCheckBox(self.adapters_frame, text=f"{a.name}{net}  —  {dns.describe_servers(a)}", variable=var,
                            font=ctk.CTkFont(size=13)).grid(row=i, column=0, sticky="w", pady=2)
        redirect = dns.gdpi_dns_redirect(gdpi.arguments, gdpi.state == "running") if gdpi.installed else False
        self.dns_warn.configure(
            text="⚠ GoodbyeDPI çalışıyor ve DNS'i kendi sunucusuna yönlendiriyor (--dns-addr): burada seçtiğin DNS "
                 "etkisiz kalır. Etkili olması için GoodbyeDPI'ı kapat ya da bu seçeneği içermeyen bir ayarla çalıştır."
            if redirect else "")

    # ---------------- ag'a bagli kural
    def _show_scope(self) -> None:
        nets = ", ".join(self.scope.networks) or "(henüz yok)"
        if self.scope.enabled:
            self.scope_sw.select()
            name = dns.resolve_servers(self.scope.value)[3] if self.scope.value else "?"
            text = f"Etkin: {name}" + (" (şifreli)" if self.scope.doh else "") + f" yalnızca şu ağlarda: {nets}"
        else:
            self.scope_sw.deselect()
            text = f"Güvenilen ağlar: {nets}"
        self.scope_lbl.configure(text=text)

    def current_networks(self) -> list[str]:
        return [a.network for a in self.adapters if a.network]

    def _save_scope(self, rule: dnsscope.Rule, enforce: bool) -> None:
        try:
            rule = dnsscope.validate(rule)
        except AuxyError as exc:
            self.say(str(exc), error=True)
            return
        dnsscope.save(rule)
        self.scope = rule
        self._show_scope()
        try:
            system.signal_config_changed()  # calisan ajan kurali hemen uygular
        except Exception:  # noqa: BLE001, S110 - ajan calismiyor olabilir
            pass
        if enforce and rule.enabled:
            self._dns_task(lambda: actions.dns_op("enforce"), "Ağa bağlı DNS uygulanıyor… (yönetici izni istenebilir)")
        else:
            self.refresh()

    def _scope_toggled(self) -> None:
        if self.scope_sw.get():
            self.say("Güvenilen ağları ekle, sonra 'Uygula'ya bas.")
            return
        if self.scope.enabled:
            rule = dnsscope.Rule(**{**self.scope.__dict__, "enabled": False})
            self._save_scope(rule, enforce=False)
            self.say("Ağa bağlı kural kapatıldı. Şu anki DNS'i geri almak için 'Eski haline döndür'.")

    def scope_add_current(self) -> None:
        nets = self.current_networks()
        if not nets:
            self.say("Bağlı bir ağ bulunamadı (Wi-Fi/Ethernet bağlanınca tekrar dene).", error=True)
            return
        rule = dnsscope.Rule(**{**self.scope.__dict__, "networks": [*self.scope.networks, *nets]})
        self._save_scope(rule, enforce=rule.enabled)
        self.say("Güvenilenlere eklendi: " + ", ".join(nets))

    def scope_remove_current(self) -> None:
        cur = {n.casefold() for n in self.current_networks()}
        rule = dnsscope.Rule(**{**self.scope.__dict__,
                                "networks": [n for n in self.scope.networks if n.casefold() not in cur]})
        if rule.enabled and not rule.networks:
            rule.enabled = False  # liste bosaldi: kural anlamsiz, kapat (DNS'i geri almak icin 'Eski haline dondur')
        self._save_scope(rule, enforce=rule.enabled)

    def selected_adapters(self) -> list[int]:
        return [i for i, v in self.adapter_vars.items() if v.get()]

    def _preset_changed(self, shown: str) -> None:
        if shown == CUSTOM:
            self.custom_entry.grid()
        else:
            self.custom_entry.grid_remove()
        self._sync_doh()

    def _doh_changed(self) -> None:
        self.strict_sw.configure(state="normal" if self.doh_sw.get() else "disabled")
        if not self.doh_sw.get():
            self.strict_sw.deselect()

    def _sync_doh(self) -> None:
        """Ozel (bilinmeyen) DNS icin DoH adresi yoksa anahtari kapat."""
        if self.preset_menu.get() == CUSTOM:
            try:
                template = dns.resolve_servers(self.custom_entry.get())[2]
            except Exception:  # noqa: BLE001 - yazarken gecersiz olabilir
                template = None
            if not template:
                self.doh_sw.deselect()
                self._doh_changed()

    def chosen_value(self) -> str:
        shown = self.preset_menu.get()
        return self.custom_entry.get().strip() if shown == CUSTOM else PRESET_NAMES[shown]

    def apply_dns(self) -> None:
        if self.scope_sw.get():
            value = self.chosen_value()
            doh, strict = bool(self.doh_sw.get()), bool(self.strict_sw.get())
            nets = ", ".join(self.scope.networks) or "(yok)"
            if not messagebox.askyesno("Ağa bağlı DNS", f"DNS '{self.preset_menu.get()}'" + (" (şifreli)" if doh else "")
                                       + f" yalnızca şu ağlarda kullanılacak: {nets}.\nDiğer ağlarda DNS otomatik "
                                       "(ağın kendi DNS'i) olacak.\nDevam edilsin mi?"):
                return
            self._save_scope(dnsscope.Rule(True, value, doh, strict, list(self.scope.networks)), enforce=True)
            return
        sel = self.selected_adapters()
        if not sel:
            self.say("En az bir ağ seç.", error=True)
            return
        value = self.chosen_value()
        doh, strict = bool(self.doh_sw.get()), bool(self.strict_sw.get())
        if not messagebox.askyesno("DNS'i değiştir", f"Seçili ağların DNS sunucusu '{self.preset_menu.get()}' olacak"
                                   + (" (şifreli)" if doh else "") + ".\nİstediğin zaman 'Eski haline döndür' ile geri alabilirsin."
                                   "\nUyarı: bu ayar bağlandığın HER ağda geçerli olur; kampüs/otel gibi giriş sayfalı "
                                   "ağlarda internet gelmeyebilir. Bunun için 'Yalnızca güvendiğim ağlarda'yı aç."
                                   "\nDevam edilsin mi?"):
            return
        self._dns_task(lambda: actions.dns_op("apply", value, sel, doh, strict), "DNS uygulanıyor… (yönetici izni istenebilir)")

    def reset_dns(self) -> None:
        if self.scope.enabled:  # kural acik kalirsa ajan guvenilen agda DNS'i yeniden atar: once kurali kapat
            dnsscope.save(dnsscope.Rule(**{**self.scope.__dict__, "enabled": False}))
            self.scope = dnsscope.load()
            self._show_scope()
        sel = self.selected_adapters()
        self._dns_task(lambda: actions.dns_op("reset", "", sel), "DNS eski haline döndürülüyor… (yönetici izni istenebilir)")

    def flush_dns(self) -> None:
        self._dns_task(lambda: actions.dns_op("flush"), "Önbellek temizleniyor… (yönetici izni istenebilir)")

    def _dns_task(self, fn, busy: str) -> None:
        self.say(busy)

        def done(res, exc):
            self.say(str(exc) if exc else res.message, error=exc is not None or not res.ok)
            self.refresh()

        self.app.worker.submit(fn, done)

    # ---------------- hiz testi
    def run_bench(self) -> None:
        self.bench_btn.configure(state="disabled")
        self.use_best_btn.configure(state="disabled")
        self.bench_note.configure(text="Test sürüyor…", text_color=MUTED)
        extra = [(a.v4[0], f"Şu anki ({a.name})") for a in self.adapters if a.v4]
        self.app.worker.submit(lambda: dns.benchmark(extra), self._bench_done)

    def _bench_done(self, res, exc) -> None:
        self.bench_btn.configure(state="normal")
        for w in self.bench_frame.winfo_children():
            w.destroy()
        if exc is not None:
            self.bench_note.configure(text=f"Test başarısız: {exc}", text_color=theme.BAD)
            return
        self.bench = res
        best = dns.best(res)
        self.bench_note.configure(
            text=(f"En iyi: {best.label} ({best.ms:.0f} ms)." if best else "Güvenilir sonuç bulunamadı (ağ DNS'i engelliyor olabilir)."),
            text_color=theme.GOOD if best else theme.WARN)
        self.use_best_btn.configure(state="normal" if best and dns.preset_for_address(best.server) else "disabled")
        for i, r in enumerate(res):
            ms = "yanıt yok" if r.ms is None else f"{r.ms:.0f} ms"
            flags = []
            if r.hijacked:
                flags.append("⚠ sahte yanıt")
            if r.tcp443_ms is None:
                flags.append("443 kapalı")
            if r.failed:
                flags.append(f"{r.failed}/{r.total} hata")
            color = theme.BAD if r.ms is None or r.hijacked else (theme.GOOD if best and r is best else theme.TEXT)
            ctk.CTkLabel(self.bench_frame, text=f"{r.label}", anchor="w", text_color=color).grid(row=i, column=0, sticky="w")
            ctk.CTkLabel(self.bench_frame, text=ms, anchor="e", text_color=color, width=80).grid(row=i, column=1, padx=8)
            ctk.CTkLabel(self.bench_frame, text="  ".join(flags), anchor="w", text_color=theme.WARN).grid(
                row=i, column=2, sticky="w")

    def use_best(self) -> None:
        best = dns.best(self.bench)
        key = dns.preset_for_address(best.server) if best else None
        if key:
            self.preset_menu.set(dns.PRESETS[key].name)
            self._preset_changed(dns.PRESETS[key].name)
            self.say(f"{dns.PRESETS[key].name} seçildi. Uygulamak için 'Uygula'ya bas.")

    # ---------------- gizlilik
    @staticmethod
    def _read_privacy():
        return ({k: privacy.get_flag(k) for k in privacy.FLAGS}, privacy.read_mac_randomization())

    def _show_privacy(self, res, exc) -> None:
        if exc is not None:
            self.say(f"Gizlilik ayarları okunamadı: {exc}", error=True)
            return
        flags, macs = res
        for k, sw in self.privacy_sw.items():
            (sw.select if flags[k] in (True, None) else sw.deselect)()  # kayit yok: Windows varsayilani acik
        for w in self.mac_frame.winfo_children():
            w.destroy()
        self.mac_switches = {}
        for i, (iface, on) in enumerate(macs.items()):
            box = ctk.CTkFrame(self.mac_frame, fg_color="transparent")
            box.grid(row=i, column=0, sticky="ew", padx=0, pady=2)
            box.columnconfigure(0, weight=1)
            lab = ctk.CTkFrame(box, fg_color="transparent")
            lab.grid(row=0, column=0, sticky="w", padx=18, pady=5)
            ctk.CTkLabel(lab, text=f"Rastgele Wi-Fi MAC adresi ({iface})", font=ctk.CTkFont(size=14), anchor="w").pack(anchor="w")
            ctk.CTkLabel(lab, text="Ağlarda cihazını takip etmeyi zorlaştırır. Yönetici izni ister; Wi-Fi'ye yeniden "
                                   "bağlanınca etkinleşir.", text_color=MUTED, wraplength=520, justify="left",
                         font=ctk.CTkFont(size=12), anchor="w").pack(anchor="w")
            sw = ctk.CTkSwitch(box, text="", width=46, command=lambda n=iface: self._toggle_mac(n))
            sw.grid(row=0, column=1, padx=(0, 18))
            (sw.select if on else sw.deselect)()
            self.mac_switches[iface] = sw

    def _toggle_flag(self, key: str) -> None:
        on = bool(self.privacy_sw[key].get())
        self.app.worker.submit(lambda: actions.privacy_op(f"{key}-{'on' if on else 'off'}"),
                               lambda r, e: self._plain_done(r, e))

    def _toggle_mac(self, iface: str) -> None:
        on = bool(self.mac_switches[iface].get())
        self.say("Rastgele MAC güncelleniyor… (yönetici izni istenebilir)")
        self.app.worker.submit(lambda: actions.privacy_op("mac-on" if on else "mac-off", iface),
                               lambda r, e: self._plain_done(r, e))

    def _plain_done(self, res, exc) -> None:
        self.say(str(exc) if exc else res.message, error=exc is not None or not res.ok)
        self.refresh()

    def show_trace(self) -> None:
        if not messagebox.askyesno("Ağ bilgisi", "Genel IP adresini ve ülkeni öğrenmek için Cloudflare'e (1.1.1.1) "
                                   "tek bir HTTPS isteği gönderilecek.\nDevam edilsin mi?"):
            return
        self.trace_lbl.configure(text="Soruluyor…")
        self.app.worker.submit(dns.fetch_trace, self._trace_done)

    def _trace_done(self, res, exc) -> None:
        if exc is not None:
            self.trace_lbl.configure(text=f"Alınamadı: {exc}", text_color=theme.BAD)
            return
        warp = {"on": "WARP açık", "plus": "WARP+ açık"}.get(res.get("warp", ""), "WARP kapalı")
        self.trace_lbl.configure(text=f"IP: {res.get('ip', '?')}  •  Ülke: {res.get('loc', '?')}  •  {warp}",
                                 text_color=theme.TEXT)

    # ---------------- Tor
    def _show_tor(self, res, exc, polling: bool = False) -> None:
        if exc is not None:
            self.tor_state.configure(text="● Okunamadı", text_color=theme.BAD)
            self.tor_detail.configure(text=str(exc))
            return
        st = self.tor_status = res
        self.tor_install_btn.pack_forget()
        if not st.installed:
            self.tor_state.configure(text="● Kurulu değil", text_color=MUTED)
            self.tor_detail.configure(text="Resmi Tor paketi torproject.org'dan indirilir ve SHA-256 ile doğrulanır.")
            self.tor_install_btn.pack(side="right", padx=(0, 8))
            for b in (self.tor_start_btn, self.tor_stop_btn, self.newnym_btn, self.verify_btn):
                b.configure(state="disabled")
            self.proxy_sw.configure(state="disabled")
            return
        connected = st.running and st.bootstrap >= 100
        if connected:
            self.tor_state.configure(text="● Bağlı", text_color=theme.GOOD)
            self.tor_detail.configure(text=f"Tor {st.version} • SOCKS5: 127.0.0.1:{tor.SOCKS_PORT}")
        elif st.running:
            self.tor_state.configure(text=f"◌ Bağlanıyor… %{st.bootstrap}", text_color=theme.WARN)
            self.tor_detail.configure(text=st.summary or "Tor ağına bağlanılıyor…")
            if not polling:
                self._poll_tor()
        else:
            self.tor_state.configure(text="● Durdu", text_color=theme.BAD)
            self.tor_detail.configure(text=f"Tor {st.version} kurulu.")
        self.tor_start_btn.configure(state="disabled" if st.running else "normal")
        self.tor_stop_btn.configure(state="normal" if st.running else "disabled")
        self.newnym_btn.configure(state="normal" if connected else "disabled")
        self.verify_btn.configure(state="normal" if connected else "disabled")
        self.proxy_sw.configure(state="normal" if connected else "disabled")
        (self.proxy_sw.select if tor.system_proxy_is_tor() else self.proxy_sw.deselect)()

    def _poll_tor(self, left: int = TOR_POLL_MAX) -> None:
        self._tor_token = token = object()

        def tick():
            if self._tor_token is not token:
                return

            def got(res, exc):
                if self._tor_token is not token:
                    return
                self._show_tor(res, exc, polling=True)
                if exc is None and res.running and res.bootstrap < 100 and left > 0:
                    self._poll_tor(left - 1)
                elif exc is None and res.running and res.bootstrap >= 100:
                    self.say("Tor bağlandı.")
                elif exc is None and not res.running:
                    self.say("Tor durdu (ağ engelliyor olabilir: köprü dene).", error=True)

            self.app.worker.submit(tor.status, got)

        self.after(TOR_POLL_MS, tick)

    def tor_install(self) -> None:
        if not messagebox.askyesno("Tor'u kur", "Resmi Tor Expert Bundle (~21 MB) dist.torproject.org adresinden "
                                   "indirilecek ve SHA-256 ile doğrulanacak.\nDevam edilsin mi?"):
            return
        self.say("Tor indiriliyor ve doğrulanıyor…")
        self.tor_install_btn.configure(state="disabled")

        def done(res, exc):
            self.tor_install_btn.configure(state="normal")
            self.say(str(exc) if exc else res, error=exc is not None)
            self.refresh()

        self.app.worker.submit(tor.install, done, long=True)

    def tor_start(self) -> None:
        kind = BRIDGE_MODES[self.bridge_menu.get()]
        bridges = None
        if kind:
            bridges = tor.bridge_lines(kind)
            if not bridges:
                self.say("Bu köprü türü için paketle gelen köprü bulunamadı; 'Doğrudan bağlan'ı dene.", error=True)
                return
        self.say("Tor başlatılıyor…")

        def done(res, exc):
            self.say(str(exc) if exc else res, error=exc is not None)
            self._poll_tor()

        self.app.worker.submit(lambda: tor.start(bridges), done)

    def tor_stop(self) -> None:
        self._tor_token = None
        self.app.worker.submit(tor.stop, lambda r, e: self._plain_done_tor(r, e))

    def _plain_done_tor(self, res, exc) -> None:
        self.say(str(exc) if exc else res, error=exc is not None)
        self.refresh()

    def tor_newnym(self) -> None:
        self.app.worker.submit(tor.new_identity, lambda r, e: self.say(str(e) if e else r, error=e is not None))

    def _toggle_proxy(self) -> None:
        on = bool(self.proxy_sw.get())
        self.app.worker.submit(lambda: tor.set_system_proxy(on), lambda r, e: self._plain_done_tor(r, e))

    def tor_verify(self) -> None:
        self.tor_verify_lbl.configure(text="Doğrulanıyor…", text_color=MUTED)
        self.app.worker.submit(tor.check_tor, self._verify_done)

    def _verify_done(self, res, exc) -> None:
        if exc is not None:
            self.tor_verify_lbl.configure(text=f"Doğrulanamadı: {exc}", text_color=theme.BAD)
            return
        ok = bool(res.get("IsTor"))
        self.tor_verify_lbl.configure(
            text=f"Tor üzerinden çıkıyorsun ✔  (IP {res.get('IP')})" if ok else f"Tor üzerinden ÇIKMIYOR (IP {res.get('IP')})",
            text_color=theme.GOOD if ok else theme.BAD)
