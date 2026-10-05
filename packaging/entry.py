"""PyInstaller giris noktasi: AuxySecurity.exe (pencereli) ve auxy.exe (konsol) ayni kodu calistirir."""

import sys

if __name__ == "__main__":
    # Boru/dosyaya yonlendirilmis ciktida Turkce karakter ve simgeler bozulmasin (konsolda zaten Unicode)
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "isatty") and not stream.isatty():
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
    from auxy.__main__ import main

    code = main()
    # COM nesneleri yorumlayici kapanirken (CoUninitialize sonrasi) serbest kalinca
    # "Win32 exception occurred releasing IUnknown" yazilir: once topla, sonra sert cik.
    import gc
    import os

    gc.collect()
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code if isinstance(code, int) else 0)
