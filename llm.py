# -*- coding: utf-8 -*-
"""
Integração com LLM (OpenAI) pra três melhorias opcionais do rastreador:

  1. filtrar_relevantes_llm  — descarta resultados de busca que não são
     realmente o produto procurado (além do filtro por palavras já existente
     em scraper.py).
  2. extrair_com_llm         — quando a extração normal de preço/título de
     uma página de produto falha (ex.: a loja mudou o layout), tenta ler o
     texto da página com o LLM.
  3. sugerir_termo_busca_llm — converte uma descrição em linguagem natural
     ("uma placa de vídeo boa até 2000 reais") num termo de busca objetivo.

Tudo aqui é "fail-open": se o LLM não estiver configurado/ativado, ou a
chamada falhar por qualquer motivo (sem internet, chave errada, cota
excedida), as funções devolvem um resultado neutro (não filtram nada, não
extraem nada, não sugerem nada) — nunca quebram uma busca por causa disso.
"""

import json

try:
    import llm_config as cfg
except ImportError:
    # Instalação nova (ex.: via o instalador) sem llm_config.py ainda — fica
    # como "LLM desligado" até o usuário criar o arquivo, em vez de o app
    # inteiro travar na abertura.
    class cfg:
        LLM_ATIVADO = False
        OPENAI_API_KEY = None
        OPENAI_MODELO = "gpt-4o-mini"

_cliente_cache = None


def esta_configurado():
    return bool(cfg.LLM_ATIVADO and cfg.OPENAI_API_KEY)


def _cliente():
    global _cliente_cache
    if _cliente_cache is None:
        from openai import OpenAI
        _cliente_cache = OpenAI(api_key=cfg.OPENAI_API_KEY)
    return _cliente_cache


def _chamar_json(mensagem_sistema, mensagem_usuario):
    """Chama o modelo pedindo uma resposta em JSON. Levanta exceção se algo falhar."""
    resposta = _cliente().chat.completions.create(
        model=cfg.OPENAI_MODELO,
        messages=[
            {"role": "system", "content": mensagem_sistema},
            {"role": "user", "content": mensagem_usuario},
        ],
        response_format={"type": "json_object"},
        timeout=20,
    )
    return json.loads(resposta.choices[0].message.content)


def filtrar_relevantes_llm(termo_busca, candidatos):
    """
    `candidatos`: lista de dicts com pelo menos a chave 'titulo'. Devolve a
    lista filtrada (só o que o LLM considerou o produto buscado de verdade —
    não acessório relacionado, nem outro modelo/linha, nem categoria errada),
    ou None se o LLM não estiver configurado/ativado ou a chamada falhar.

    Devolver None (em vez de "sem filtro nenhum") importa: quem chama isso é
    o único filtro de relevância da busca quando o LLM está ativado (a
    checagem por palavras não roda mais nesse caso) — se o LLM falhar por
    qualquer motivo, quem chama precisa saber pra cair no filtro por
    palavras, em vez de deixar passar candidatos sem filtro nenhum.
    """
    if not esta_configurado() or not candidatos:
        return None

    try:
        itens_numerados = "\n".join(f"{i}: {c['titulo']}" for i, c in enumerate(candidatos))
        dados = _chamar_json(
            "Você filtra resultados de busca de loja de hardware/eletrônicos. "
            "Responda só com JSON, sem texto fora do JSON.",
            f'Termo buscado: "{termo_busca}"\n\n'
            f"Títulos encontrados:\n{itens_numerados}\n\n"
            "Quais desses índices são realmente o produto buscado (não são acessório "
            "relacionado, nem outro modelo/linha, nem categoria errada)? Sinônimos e "
            "abreviações do MESMO produto contam como igual (ex.: \"QHD\" e \"QuadHD\" "
            "são a mesma coisa) — mas sufixos como Ti, Super, XT, Pro, Max, SE, GT, "
            "\"non-K\" indicam um modelo DIFERENTE (quase sempre mais caro ou mais "
            "barato), então se o termo buscado tem um desses sufixos, só conta como "
            "relevante o título que também tem o MESMO sufixo — e vice-versa (se o "
            "termo buscado NÃO tem o sufixo, um título COM o sufixo também não conta). "
            'Responda: {"relevantes": [lista de índices inteiros]}',
        )
        indices = set(dados.get("relevantes", []))
        if not indices:
            return candidatos  # resposta vazia/estranha — não descarta tudo à toa
        return [c for i, c in enumerate(candidatos) if i in indices]
    except Exception:
        return None


def extrair_com_llm(texto_pagina, termo_busca=None):
    """
    Tenta achar título + preço de uma página de produto a partir do texto
    visível dela, pra quando a extração normal (HTML/JSON-LD) falhar.
    Devolve (titulo, preco) ou (None, None) se não conseguir.
    """
    if not esta_configurado() or not texto_pagina:
        return None, None

    try:
        texto_recortado = texto_pagina[:6000]
        contexto = f' (procurando por "{termo_busca}")' if termo_busca else ""
        dados = _chamar_json(
            "Você lê o texto de uma página de produto de loja online e extrai o nome do "
            "produto e o preço final em reais. Responda só com JSON, sem texto fora do JSON.",
            f"Texto da página{contexto}:\n\n{texto_recortado}\n\n"
            'Responda: {"titulo": "...", "preco": 1234.56} — "preco" é só o número '
            '(sem "R$", com ponto decimal). Se não achar um preço claro, use {"titulo": null, "preco": null}.',
        )
        titulo = dados.get("titulo") or None
        preco = dados.get("preco")
        preco = float(preco) if isinstance(preco, (int, float)) else None
        return titulo, preco
    except Exception:
        return None, None


def sugerir_melhoria_termo_llm(termo_digitado):
    """
    Olha pro que a pessoa digitou em "O que procurar" e decide: já é um bom
    termo de busca objetivo (nome de produto/modelo)? Se sim, devolve None
    (não sugere nada — a busca segue normal, sem atraso perceptível). Se for
    uma descrição vaga, um pedido em linguagem natural ("uma placa de vídeo
    boa até 2000 reais"), ou puder ficar mais específico, devolve o termo
    sugerido pra o app perguntar "usar esse em vez desse?" antes de buscar.
    """
    if not esta_configurado() or not termo_digitado:
        return None

    try:
        dados = _chamar_json(
            "Você ajuda a melhorar termos de busca de loja de hardware/eletrônicos "
            "brasileira. Responda só com JSON, sem texto fora do JSON.",
            f'A pessoa digitou isto pra buscar: "{termo_digitado}"\n\n'
            "Se isso já é um termo de busca objetivo (nome de produto/modelo, do jeito "
            "que se digitaria na busca de uma loja), não sugira nada. Se for uma "
            "descrição vaga, um pedido em linguagem natural, ou puder ficar mais "
            "específico pra achar o produto certo, sugira UM termo de busca melhor "
            "(curto, objetivo, sem frases, sem explicação). "
            'Responda: {"sugestao": "termo melhor" ou null}',
        )
        sugestao = dados.get("sugestao")
        if not isinstance(sugestao, str):
            return None
        sugestao = sugestao.strip()
        if not sugestao or sugestao.lower() == termo_digitado.strip().lower():
            return None
        return sugestao
    except Exception:
        return None


# Campos esperados por categoria, pra checagem de compatibilidade no Montar
# PC (ver compatibilidade.py). Cada valor é (descrição pro prompt, chave no JSON).
_CAMPOS_COMPAT_POR_CATEGORIA = {
    "processador": ("o socket do processador, ex.: 'AM5', 'AM4', 'LGA1700', 'LGA1200'", "socket"),
    "placa_mae": (
        "o socket que ela aceita (ex.: 'AM5', 'LGA1700') e o tipo de memória RAM "
        "que ela aceita ('DDR4' ou 'DDR5')",
        None,
    ),
    "memoria_ram": ("o tipo da memória ('DDR4' ou 'DDR5')", "tipo"),
    "placa_video": ("a potência de fonte recomendada pelo fabricante, em watts (só o número)", "watts_recomendados"),
    "fonte": ("a potência dela, em watts (só o número)", "watts"),
}


def extrair_specs_compatibilidade(categoria, nome_produto):
    """
    Pede pra IA estimar, a partir do NOME do produto (não há uma base de
    dados oficial de peças aqui), os dados técnicos relevantes pra checar
    compatibilidade no Montar PC — socket, tipo de RAM, wattagem. É uma
    estimativa, não uma fonte oficial: pode vir incompleta ou errada se o
    nome do produto não tiver informação suficiente.

    Devolve um dict (pode ter campos faltando/None) ou {} se a categoria não
    é relevante pra compatibilidade, ou None se a IA não está configurada ou
    a chamada falhar.
    """
    if categoria not in _CAMPOS_COMPAT_POR_CATEGORIA:
        return {}
    if not esta_configurado() or not nome_produto:
        return None

    try:
        if categoria == "placa_mae":
            pedido = (
                "o socket que ela aceita (ex.: \"AM5\", \"AM4\", \"LGA1700\", \"LGA1200\", ou null se não "
                "der pra saber) e o tipo de memória RAM que ela aceita (\"DDR4\", \"DDR5\", ou null)"
            )
            formato = '{"socket": "AM5" ou null, "tipo_ram": "DDR5" ou null}'
        else:
            descricao, chave = _CAMPOS_COMPAT_POR_CATEGORIA[categoria]
            pedido = descricao
            formato = f'{{"{chave}": valor ou null}}'

        dados = _chamar_json(
            "Você estima especificações técnicas de hardware de PC a partir do nome de um produto, "
            "pra checar compatibilidade entre peças. Se não der pra saber com confiança a partir do "
            "nome, responda null pro campo — não invente. Responda só com JSON, sem texto fora do JSON.",
            f'Produto (categoria "{categoria}"): "{nome_produto}"\n\n'
            f"Estime {pedido}.\n"
            f"Responda: {formato}",
        )
        return dados if isinstance(dados, dict) else {}
    except Exception:
        return None
