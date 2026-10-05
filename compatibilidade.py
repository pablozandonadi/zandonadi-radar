# -*- coding: utf-8 -*-
"""
Checagem de compatibilidade entre peças de um "Montar PC".

As specs (socket, tipo de RAM, wattagem) vêm de uma ESTIMATIVA da IA a
partir do nome do produto — não existe uma base de dados oficial de peças
aqui. Por isso isso aqui gera só AVISOS, nunca bloqueia nada: pode faltar
informação (nome do produto não deixa claro) ou a IA pode errar. Sem IA
configurada, essa checagem simplesmente não acha nada pra avisar.
"""

import re

import database as db
import llm


def _specs_produto(produto):
    """Specs já calculadas (cache em produtos.specs_compat) ou calcula
    agora pela IA e salva o cache. Devolve {} se a categoria do produto não
    é relevante pra compatibilidade, ou None se a IA está indisponível."""
    specs = db.obter_specs_compat(produto["id"])
    if specs is not None:
        return specs
    specs = llm.extrair_specs_compatibilidade(produto["categoria"], produto["nome"])
    if specs is None:
        return None
    db.definir_specs_compat(produto["id"], specs)
    return specs


def _normalizar_socket(valor):
    return "".join(ch for ch in str(valor).upper() if ch.isalnum())


def _para_numero(valor):
    if valor is None:
        return None
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        encontrado = re.search(r"\d+(\.\d+)?", str(valor))
        return float(encontrado.group()) if encontrado else None


def checar_build(itens_build):
    """
    `itens_build`: dict {categoria_chave: item}, no formato que
    db.listar_itens_build devolve (cada item tem "produto_id" quando a
    categoria tem uma peça escolhida). Faz chamadas de rede (IA) pra
    qualquer peça ainda sem specs em cache — pode demorar alguns segundos;
    chame isso numa thread separada, nunca direto na tela.

    Devolve uma lista de avisos (strings) — vazia se não achou nenhuma
    incompatibilidade, ou se não tem specs suficientes pra comparar.
    """
    specs_por_categoria = {}
    for categoria, item in itens_build.items():
        produto_id = item.get("produto_id") if item else None
        if not produto_id:
            continue
        produto = db.obter_produto(produto_id)
        if not produto:
            continue
        specs = _specs_produto(produto)
        if specs:
            specs_por_categoria[categoria] = (produto["nome"], specs)

    avisos = []

    cpu = specs_por_categoria.get("processador")
    placa = specs_por_categoria.get("placa_mae")
    if cpu and placa:
        socket_cpu, socket_placa = cpu[1].get("socket"), placa[1].get("socket")
        if socket_cpu and socket_placa and _normalizar_socket(socket_cpu) != _normalizar_socket(socket_placa):
            avisos.append(
                f"🔌 Socket diferente: “{cpu[0]}” é {socket_cpu}, mas “{placa[0]}” é {socket_placa}."
            )

    ram = specs_por_categoria.get("memoria_ram")
    if ram and placa:
        tipo_ram, tipo_placa = ram[1].get("tipo"), placa[1].get("tipo_ram")
        if tipo_ram and tipo_placa and str(tipo_ram).upper() != str(tipo_placa).upper():
            avisos.append(
                f"🧠 Tipo de memória diferente: “{ram[0]}” é {tipo_ram}, mas “{placa[0]}” "
                f"aceita {tipo_placa}."
            )

    gpu = specs_por_categoria.get("placa_video")
    fonte = specs_por_categoria.get("fonte")
    if gpu and fonte:
        watts_gpu = _para_numero(gpu[1].get("watts_recomendados"))
        watts_fonte = _para_numero(fonte[1].get("watts"))
        if watts_gpu and watts_fonte and watts_fonte < watts_gpu:
            avisos.append(
                f"⚡ Fonte pode ser fraca: “{fonte[0]}” tem {int(watts_fonte)}W, mas “{gpu[0]}” "
                f"recomenda pelo menos {int(watts_gpu)}W."
            )

    return avisos
