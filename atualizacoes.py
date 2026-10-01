# -*- coding: utf-8 -*-
"""
Checagem de atualização via GitHub Releases (ver REPO_GITHUB em config.py).

Fail-open, igual o resto do app: qualquer problema (sem internet, GitHub
fora do ar, repositório mudou) só faz a checagem devolver None — nunca
trava nem atrapalha o uso normal do programa.
"""

import os
import tempfile

import requests

from config import REPO_GITHUB, VERSAO_APP


def _versao_para_tupla(versao):
    """'v1.2.10' ou '1.2.10' -> (1, 2, 10), pra comparar número com número
    (string pura ordenaria '10' antes de '9')."""
    partes = versao.strip().lstrip("vV").split(".")
    numeros = []
    for p in partes:
        digitos = "".join(ch for ch in p if ch.isdigit())
        numeros.append(int(digitos) if digitos else 0)
    return tuple(numeros)


def verificar_atualizacao():
    """
    Consulta a última release do GitHub. Devolve um dict
    {"versao", "url_instalador", "notas", "url_release"} se houver uma
    versão mais nova que VERSAO_APP com um instalador (.exe) anexado, ou
    None se já está atualizado, o repositório não tem releases, ou algo
    deu errado (sem internet etc.).
    """
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{REPO_GITHUB}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        dados = resp.json()

        tag = dados.get("tag_name") or ""
        if not tag:
            return None
        if _versao_para_tupla(tag) <= _versao_para_tupla(VERSAO_APP):
            return None

        url_instalador = None
        for asset in dados.get("assets", []):
            if (asset.get("name") or "").lower().endswith(".exe"):
                url_instalador = asset.get("browser_download_url")
                break
        if not url_instalador:
            return None

        return {
            "versao": tag,
            "url_instalador": url_instalador,
            "notas": dados.get("body") or "",
            "url_release": dados.get("html_url") or "",
        }
    except Exception:
        return None


def baixar_instalador(url_instalador, callback_progresso=None):
    """
    Baixa o instalador novo pra uma pasta temporária. Devolve o caminho do
    arquivo baixado, ou None se falhar. `callback_progresso(pct_0_a_100)`,
    se passado, é chamado conforme o download avança.
    """
    try:
        resp = requests.get(url_instalador, stream=True, timeout=30)
        if resp.status_code != 200:
            return None

        total = int(resp.headers.get("content-length") or 0)
        baixado = 0
        destino = os.path.join(tempfile.gettempdir(), "ZandonadiRadarSetup_novo.exe")

        with open(destino, "wb") as f:
            for pedaco in resp.iter_content(chunk_size=262144):
                if not pedaco:
                    continue
                f.write(pedaco)
                baixado += len(pedaco)
                if callback_progresso and total:
                    callback_progresso(min(100, int(baixado * 100 / total)))

        return destino
    except Exception:
        return None
