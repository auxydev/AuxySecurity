"""Ön ayarlar sayfasi: tek tikla birden cok ayari birlikte degistiren profiller."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from auxy.core import actions, presets
from auxy.gui import theme
from auxy.gui.widgets import page_header

ICONS = {"hiz": "⚡", "guvenilir": "🛡", "gizli": "🕶", "tor": "🧅", "yurt": "🏠"}
ACCENTS = {"hiz": "#f59e0b", "guvenilir": "#16a34a", "gizli": "#7c3aed", "tor": "#6d28d9", "yurt": "#0891b2"}


class PresetsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.busy = False

        head = page_header(self, "Ön ayarlar", "Tek tıkla birden fazla ayarı birlikte değiştir. Önce ne değişeceğini "
                                               "gösteririz, sen onaylarsın; istediğin an geri alırsın.")
        self.message = head.message
        self.message.pack(side="right", padx=(0, 12))

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # ---- etkin ön ayar
        bar = ctk.CTkFrame(body, corner_radius=14, border_width=1)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14), padx=(0, 6))
        bar.columnconfigure(0, weight=1)
        self.active_lbl = ctk.CTkLabel(bar, text="Etkin ön ayar: yok", anchor="w", font=ctk.CTkFont(size=15, weight="bold"))
        self.active_lbl.grid(row=0, column=0, sticky="w", padx=18, pady=14)
        self.revert_btn = ctk.CTkButton(bar, text="Önceki ayarlara dön", width=170, height=34, fg_color="transparent",
                                        border_width=1, text_color=theme.TEXT, hover_color=theme.SURFACE_ALT,
                                        command=self.revert)
        self.revert_btn.grid(row=0, column=1, padx=(0, 18))

        # ---- kartlar
        self.buttons: dict[str, ctk.CTkButton] = {}
        self.cards: dict[str, ctk.CTkFrame] = {}
        for i, (key, info) in enumerate(presets.PRESETS.items()):
            card = ctk.CTkFrame(body, corner_radius=14, border_width=1)
            card.grid(row=1 + i // 2, column=i % 2, sticky="nsew", pady=(0, 14), padx=(0, 6) if i % 2 == 0 else (6, 6))
            card.columnconfigure(0, weight=1)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 0))
            ctk.CTkLabel(top, text=ICONS[key], width=40, height=40, corner_radius=20, fg_color=ACCENTS[key],
                         text_color="white", font=ctk.CTkFont(size=18)).pack(side="left")
            names = ctk.CTkFrame(top, fg_color="transparent")
            names.pack(side="left", padx=12)
            ctk.CTkLabel(names, text=info.name, anchor="w", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w")
            ctk.CTkLabel(names, text=info.tagline, anchor="w", justify="left", wraplength=250, text_color=theme.MUTED,
                         font=ctk.CTkFont(size=12)).pack(anchor="w")
            ctk.CTkLabel(card, text="\n".join(f"•  {b}" for b in info.bullets), anchor="w", justify="left", wraplength=330,
                         text_color=theme.TEXT).grid(row=1, column=0, sticky="w", padx=18, pady=(12, 8))
            btn = ctk.CTkButton(card, text="Uygula", height=36, fg_color=ACCENTS[key],
                                command=lambda k=key: self.start(k))
            btn.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
            self.buttons[key] = btn
            self.cards[key] = card

    # ---- gorunum ----
    def say(self, text: str, error: bool = False) -> None:
        self.message.configure(text=text, text_color=theme.BAD if error else theme.TEXT)

    def refresh(self) -> None:
        active = presets.load_record().get("active", "")
        if active in presets.PRESETS:
            self.active_lbl.configure(text=f"Etkin ön ayar: {presets.PRESETS[active].name}")
        else:
            self.active_lbl.configure(text="Etkin ön ayar: yok (ayarların kendi hâlinde)")
        self.revert_btn.configure(state="normal" if active and not self.busy else "disabled")
        for key, card in self.cards.items():
            card.configure(border_color=ACCENTS[key] if key == active else theme.BORDER,
                           border_width=2 if key == active else 1)
            self.buttons[key].configure(text="✔ Etkin: yeniden uygula" if key == active else "Uygula",
                                        state="disabled" if self.busy else "normal")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.refresh()

    # ---- uygulama ----
    def start(self, key: str) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.say("Plan hazırlanıyor… (ağ ölçümü birkaç saniye sürebilir)")

        def plan():
            state = presets.capture_state()
            best = presets.resolve_best(state) if presets.SPECS[key]["dns"] == "best" else None
            return state, presets.build_plan(key, state, best)

        self.app.worker.submit(plan, lambda res, exc: self._plan_ready(key, res, exc), long=True)

    def _plan_ready(self, key: str, res, exc) -> None:
        if exc is not None:
            self._set_busy(False)
            self.say(f"Plan hazırlanamadı: {exc}", error=True)
            return
        state, plan = res
        if not plan.changes:
            self._set_busy(False)
            self.say("Değişecek bir şey yok: " + (" ".join(plan.notes) or "ayarlar zaten bu ön ayarda."))
            return
        if not messagebox.askyesno(presets.PRESETS[key].name, presets.describe(plan)):
            self._set_busy(False)
            self.say("İptal edildi; hiçbir şey değişmedi.")
            return
        self.say("Uygulanıyor… (yönetici izni istenebilir)")
        self.app.worker.submit(lambda: presets.execute(plan, state, actions.preset_admin), self._done, long=True)

    def revert(self) -> None:
        if self.busy:
            return
        self._set_busy(True)

        def plan():
            state = presets.capture_state()
            return state, presets.revert_plan(state)

        def ready(res, exc):
            if exc is not None:
                self._set_busy(False)
                self.say(f"Plan hazırlanamadı: {exc}", error=True)
                return
            state, rplan = res
            if not rplan.changes:
                presets.state_path().unlink(missing_ok=True)
                self._set_busy(False)
                self.say("Geri alınacak bir şey kalmamış.")
                return
            text = "Şunlar önceki haline döndürülecek:\n\n" + "\n".join(
                f"• {c.label}: {c.before} → {c.after}" for c in rplan.changes) + "\n\nDevam edilsin mi?"
            if not messagebox.askyesno("Önceki ayarlara dön", text):
                self._set_busy(False)
                return
            self.say("Geri alınıyor… (yönetici izni istenebilir)")
            self.app.worker.submit(lambda: presets.execute_revert(rplan, state, actions.preset_admin), self._done, long=True)

        self.app.worker.submit(plan, ready, long=True)

    def _done(self, results, exc) -> None:
        self._set_busy(False)
        if exc is not None:
            self.say(str(exc), error=True)
            return
        ok, msg = presets.summarize(results)
        self.say(msg, error=not ok)
