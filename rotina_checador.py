# -*- coding: utf-8 -*-
"""
Ponto de entrada SEM interface gráfica — quem chama isso é a Tarefa
Agendada do Windows ("ZandonadiRadar_Rotinas"), a cada ~15 minutos, mesmo
com o programa fechado.

Confere se alguma rotina cadastrada no app está na hora de rodar e, se
estiver, busca os preços daquele PC de novo. Não abre nenhuma janela.

Não precisa rodar isso manualmente — use o botão "▶ Rodar agora" dentro do
programa se quiser testar uma rotina na hora.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db
from config import BASE_DIR
from rotinas import descricao_alvo, executar_rotina, horario_pendente

LOG_PATH = os.path.join(BASE_DIR, "rotinas.log")


def _log(mensagem):
    linha = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {mensagem}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha)
    except OSError:
        pass


def main():
    db.inicializar_banco()
    agora = datetime.now()
    devidas = [(r, horario_pendente(r, agora)) for r in db.listar_rotinas()]
    devidas = [(r, h) for r, h in devidas if h is not None]

    for rotina, horario in devidas:
        alvo = descricao_alvo(rotina)
        _log(f"Rodando rotina de ‘{alvo}’ ({horario})...")
        try:
            ok = executar_rotina(rotina, log_fn=_log, horario=horario)
            if ok:
                _log(f"Rotina de ‘{alvo}’ concluída.")
            else:
                _log(f"Rotina de ‘{alvo}’ pulada: o alvo não existe mais.")
        except Exception as e:
            _log(f"Erro rodando rotina de ‘{alvo}’: {e!r}")


if __name__ == "__main__":
    main()
