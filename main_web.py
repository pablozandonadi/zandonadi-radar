# -*- coding: utf-8 -*-
"""
Ponto de entrada do Zandonadi Radar — interface em HTML/CSS/JS (pasta web/)
rodando dentro de uma janela nativa via PyWebView.

Rode com: python main_web.py
"""
import os
import sys

# Rodando como .exe congelado (instalado via o instalador): llm_config.py e
# email_config.py ficam de fora do pacote de propósito (continuam editáveis
# como arquivo de texto comum do lado do .exe, sem precisar recompilar pra
# trocar uma chave/senha) — sem isso no sys.path, `import llm_config`
# (dentro de llm.py) e `import email_config` (dentro de notificacoes.py)
# não achariam o arquivo.
if getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(sys.executable))
    # Sem console (PyInstaller --windowed) stdout/stderr vêm como None e
    # qualquer print/log de biblioteca quebraria.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

import webview

import database as db
from web_api import API

# Onde ficam web/ e icone.ico: no PyInstaller, dentro do pacote (sys._MEIPASS);
# rodando do código-fonte, ao lado deste arquivo.
if getattr(sys, "frozen", False):
    PASTA_RECURSOS = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    PASTA_RECURSOS = os.path.dirname(os.path.abspath(__file__))

if sys.platform == "win32":
    # Sem isso, o Windows agrupa a barra de tarefas pelo AppUserModelID de
    # python.exe e mostra o ícone do Python em vez do ícone da janela.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZandonadiRadar.App")
    except Exception:
        pass


def main():
    if "--rotina-checador" in sys.argv:
        # Chamado pela Tarefa Agendada do Windows quando o app está
        # "congelado" (instalado via o instalador) — roda só a checagem de
        # rotinas, sem abrir nenhuma janela, e sai. Ver tarefas_agendadas.py.
        import rotina_checador
        rotina_checador.main()
        return

    db.inicializar_banco()
    api = API()
    janela = webview.create_window(
        "Zandonadi Radar",
        os.path.join(PASTA_RECURSOS, "web", "index.html"),
        js_api=api,
        width=1280,
        height=800,
        min_size=(900, 600),
        background_color="#14171c",
    )
    api._window = janela
    # `icon` faz o WinForms usar o ícone do app em vez do do python.exe; o
    # primeiro argumento roda numa thread própria depois que a janela abre
    # (é o reforço que roda rotinas vencidas enquanto o app está aberto).
    webview.start(api._loop_rotinas_em_segundo_plano, icon=os.path.join(PASTA_RECURSOS, "icone.ico"))


if __name__ == "__main__":
    main()
