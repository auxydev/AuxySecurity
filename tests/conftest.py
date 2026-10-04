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
