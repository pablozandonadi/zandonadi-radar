# -*- coding: utf-8 -*-
"""
Tarefa Agendada do Windows que roda o checador de rotinas (rotina_checador.py)
a cada 15 minutos, mesmo com o programa fechado. Compartilhado entre main.py
(Tkinter) e web_api.py (PyWebView) -- as duas interfaces usam a mesma rotina
de fundo.
"""

import os
import subprocess
import sys

NOME_TAREFA_AGENDADA = "ZandonadiRadar_Rotinas"


def _caminho_checador():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rotina_checador.py")


def _caminho_pythonw():
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def _comando_tarefa_agendada():
    """
    Comando que a Tarefa Agendada do Windows roda a cada 15 minutos. Rodando
    de código-fonte (`python main.py`/`python main_web.py`), é o
    pythonw.exe chamando rotina_checador.py direto. Já "congelado"
    (instalado via o instalador, sem Python separado), não existe um
    rotina_checador.py solto pra chamar -- o próprio .exe principal já leva
    esse código embutido, então a tarefa roda o mesmo .exe com um argumento
    especial (ver main(), em main.py) que faz ele rodar só a checagem, sem
    abrir a janela.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --rotina-checador'
    return f'"{_caminho_pythonw()}" "{_caminho_checador()}"'


def garantir_tarefa_agendada():
    """
    Cria (ou atualiza) uma Tarefa Agendada do Windows que roda o checador de
    rotinas a cada 15 minutos, mesmo com o programa fechado. Silenciosa se
    falhar (ex.: não é Windows, ou schtasks sem permissão) -- nesse caso as
    rotinas só rodam enquanto o app estiver aberto, ficam só salvas.
    """
    if sys.platform != "win32":
        return False
    comando = _comando_tarefa_agendada()
    try:
        resultado = subprocess.run(
            ["schtasks", "/create", "/tn", NOME_TAREFA_AGENDADA, "/tr", comando,
             "/sc", "minute", "/mo", "15", "/f"],
            capture_output=True, text=True, timeout=15,
        )
        return resultado.returncode == 0
    except Exception:
        return False


def remover_tarefa_agendada():
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", NOME_TAREFA_AGENDADA, "/f"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        pass


def tarefa_agendada_existe():
    if sys.platform != "win32":
        return False
    try:
        resultado = subprocess.run(
            ["schtasks", "/query", "/tn", NOME_TAREFA_AGENDADA],
            capture_output=True, text=True, timeout=10,
        )
        return resultado.returncode == 0
    except Exception:
        return False
