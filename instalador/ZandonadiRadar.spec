# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller do Zandonadi Radar (interface nova, main_web.py).
# Não rode direto — use instalador\gerar_instalador.ps1, que também monta o
# instalador (Inno Setup) e deixa os arquivos temporários do build fora da
# pasta sincronizada do Google Drive.
import os

from PyInstaller.utils.hooks import collect_all

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(RAIZ, "icone.ico"), "."),
    (os.path.join(RAIZ, "icone.png"), "."),
    (os.path.join(RAIZ, "web"), "web"),
]
binaries = []
hiddenimports = ["clr", "rotina_checador"]

# Pacotes que carregam arquivos/DLLs próprios que o PyInstaller sozinho não acha.
# webview/pythonnet/clr_loader = a janela (WinForms + WebView2 via .NET).
for pacote in ("curl_cffi", "openai", "selenium", "webview", "pythonnet", "clr_loader"):
    d, b, h = collect_all(pacote)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(RAIZ, "main_web.py")],
    pathex=[RAIZ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # llm_config/email_config ficam de fora de propósito (credenciais — o
    # instalador gera esses arquivos do lado do .exe). O resto é peso morto
    # da interface antiga (Tkinter/matplotlib/bandeja) que a nova não usa.
    excludes=[
        "llm_config", "email_config",
        "tkinter", "_tkinter", "matplotlib", "numpy", "PIL", "pystray", "reportlab",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZandonadiRadar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX corrompe DLLs .NET (pythonnet/WebView2)
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(RAIZ, "icone.ico")],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ZandonadiRadar",
)
