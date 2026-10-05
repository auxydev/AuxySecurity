"""Ortak test duzeni: tum GUI testleri TEK bir Tk kokunu paylasir.

Ayni surecte art arda Tk() acip kapatmak (Windows Store Python + customtkinter + tkdnd) Tcl baslatma
hatasi verebiliyor; bu yuzden pencere oturum basina bir kez olusturulur, her test kendi durumunu geri alir.
"""

import os

import pytest


@pytest.fixture(scope="session")
def gui_root(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("AUXY_HOME", str(tmp_path_factory.mktemp("gui_home")))  # gercek ayarlara/kasaya dokunma
    mp.setenv("AUXY_INSTANCE", "_gui_tests")
    from auxy.gui import app as gui

    a = gui.App()
    a.update()
    yield a
    a.destroy()
    mp.undo()


@pytest.fixture(scope="session", autouse=True)
def keep_tray_icons_alive():
    """pystray, pencere sinif adini nesnenin id()'sinden turetir; testlerde cok sayida Icon olusturulup birakilinca
    cop toplayici bir nesneyi silip AYNI id'yi yenisine verebilir ve "WinError 1410: Sinif zaten var" cikar
    (kirilgan test). Uretimde tek Icon vardir; testlerde nesneleri oturum boyunca canli tutariz."""
    import pystray

    keep = []
    original = pystray.Icon.__init__

    def init(self, *a, **k):
        keep.append(self)
        original(self, *a, **k)

    pystray.Icon.__init__ = init
    yield
    pystray.Icon.__init__ = original


@pytest.fixture(autouse=True)
def no_real_dialogs(monkeypatch):
    """Testte GERCEK bir diyalog (messagebox/filedialog) acilirsa test HATA verir; sessizce takilmaz ya da
    kullanicinin ekraninda pencere acmaz. Diyalog gereken testler kendi sahtesini monkeypatch ile koyar."""
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    def forbid(name):
        def _f(*a, **k):
            raise AssertionError(f"Testte GERCEK diyalog acildi: {name} (monkeypatch ile sahtele)")
        return _f

    for n in ("askyesno", "askyesnocancel", "askokcancel", "askretrycancel", "askquestion",
              "showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(mb, n, forbid(n))
    for n in ("askopenfilename", "askopenfilenames", "asksaveasfilename", "askdirectory"):
        monkeypatch.setattr(fd, n, forbid(n))


@pytest.fixture
def app(gui_root):
    """Her test icin: pencere + tarama sayfasi durumunu geri alir."""
    a = gui_root
    page = a.pages["scan"]
    saved = (page.manager.run, page.start, page.scan_paths)
    page._cancel_all = False
    yield a
    page.manager.run, page.start, page.scan_paths = saved
    page._set_busy(False)
    a.update()


def has_display() -> bool:
    return bool(os.environ.get("SESSIONNAME") or os.name == "nt")
