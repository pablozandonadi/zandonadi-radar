# -*- coding: utf-8 -*-
"""
Camada de banco de dados (SQLite) do Rastreador de Preços.

Tabelas:
  produtos        -> itens que o usuário decidiu acompanhar (ex: "Ryzen 7 5700X" / categoria processador)
  precos          -> cada preço encontrado em cada busca, por loja, com data/hora (histórico)
  builds          -> "PCs" que o usuário está montando
  build_itens     -> qual produto está em cada slot/categoria de um build
  build_totais    -> histórico do valor total calculado de cada build
"""

import sqlite3
from datetime import datetime

from config import DB_PATH


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _colunas(conn, tabela):
    cur = conn.execute(f"PRAGMA table_info({tabela})")
    return {linha[1] for linha in cur.fetchall()}


def inicializar_banco():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT NOT NULL,
            nome TEXT NOT NULL,
            termo_busca TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            modo TEXT NOT NULL DEFAULT 'busca',
            url_fixa TEXT
        )
    """)

    # Migração para bancos criados antes dessas colunas existirem.
    colunas_produtos = _colunas(conn, "produtos")
    if "modo" not in colunas_produtos:
        cur.execute("ALTER TABLE produtos ADD COLUMN modo TEXT NOT NULL DEFAULT 'busca'")
    if "url_fixa" not in colunas_produtos:
        cur.execute("ALTER TABLE produtos ADD COLUMN url_fixa TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS precos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            loja TEXT NOT NULL,
            titulo TEXT,
            preco REAL NOT NULL,
            url TEXT,
            buscado_em TEXT NOT NULL,
            FOREIGN KEY (produto_id) REFERENCES produtos (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS builds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS build_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            build_id INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            produto_id INTEGER,
            loja TEXT,
            titulo TEXT,
            preco REAL,
            url TEXT,
            atualizado_em TEXT,
            FOREIGN KEY (build_id) REFERENCES builds (id) ON DELETE CASCADE,
            FOREIGN KEY (produto_id) REFERENCES produtos (id) ON DELETE SET NULL,
            UNIQUE (build_id, categoria)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS build_totais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            build_id INTEGER NOT NULL,
            total REAL NOT NULL,
            calculado_em TEXT NOT NULL,
            FOREIGN KEY (build_id) REFERENCES builds (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rotinas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alvo_tipo TEXT NOT NULL DEFAULT 'build',
            build_id INTEGER,
            alvo_categoria TEXT,
            horarios TEXT NOT NULL DEFAULT '09:00',
            repetir INTEGER NOT NULL DEFAULT 1,
            dias_semana TEXT,
            data_unica TEXT,
            ativa INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL,
            ultima_execucao TEXT,
            ultimo_horario TEXT,
            alerta_email TEXT,
            alerta_total_abaixo REAL,
            alertar_menor_preco INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (build_id) REFERENCES builds (id) ON DELETE CASCADE
        )
    """)

    # Migração pra bancos criados antes dos campos de alerta existirem.
    colunas_rotinas = _colunas(conn, "rotinas")
    if "alerta_email" not in colunas_rotinas:
        cur.execute("ALTER TABLE rotinas ADD COLUMN alerta_email TEXT")
    if "alerta_total_abaixo" not in colunas_rotinas:
        cur.execute("ALTER TABLE rotinas ADD COLUMN alerta_total_abaixo REAL")
    if "alertar_menor_preco" not in colunas_rotinas:
        cur.execute("ALTER TABLE rotinas ADD COLUMN alertar_menor_preco INTEGER NOT NULL DEFAULT 0")

    # Migração pra bancos criados antes de rotina poder checar uma categoria
    # inteira ou "tudo" (não só um PC montado) e antes de ter mais de um
    # horário por dia. `build_id` tinha NOT NULL (só fazia sentido pra PC) —
    # como SQLite não altera uma coluna existente pra aceitar NULL, a tabela
    # precisa ser recriada do zero (preservando os dados) nesse caso.
    colunas_rotinas = _colunas(conn, "rotinas")
    if "alvo_tipo" not in colunas_rotinas:
        cur.execute("ALTER TABLE rotinas RENAME TO rotinas_antiga")
        cur.execute("""
            CREATE TABLE rotinas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alvo_tipo TEXT NOT NULL DEFAULT 'build',
                build_id INTEGER,
                alvo_categoria TEXT,
                horarios TEXT NOT NULL DEFAULT '09:00',
                repetir INTEGER NOT NULL DEFAULT 1,
                dias_semana TEXT,
                data_unica TEXT,
                ativa INTEGER NOT NULL DEFAULT 1,
                criado_em TEXT NOT NULL,
                ultima_execucao TEXT,
                ultimo_horario TEXT,
                alerta_email TEXT,
                alerta_total_abaixo REAL,
                alertar_menor_preco INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (build_id) REFERENCES builds (id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            INSERT INTO rotinas (
                id, alvo_tipo, build_id, horarios, repetir, dias_semana, data_unica,
                ativa, criado_em, ultima_execucao, alerta_email, alerta_total_abaixo, alertar_menor_preco
            )
            SELECT
                id, 'build', build_id, hora, repetir, dias_semana, data_unica,
                ativa, criado_em, ultima_execucao, alerta_email, alerta_total_abaixo, alertar_menor_preco
            FROM rotinas_antiga
        """)
        cur.execute("DROP TABLE rotinas_antiga")

    conn.commit()
    conn.close()


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# Produtos rastreados
# --------------------------------------------------------------------------

def adicionar_produto(categoria, nome, termo_busca, modo="busca", url_fixa=None):
    """
    `modo` é 'busca' (padrão — pesquisa o termo em todas as lojas) ou 'url'
    (produto cadastrado a partir de um link direto — "Atualizar preços"
    volta sempre nesse mesmo link, em vez de pesquisar).
    """
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO produtos (categoria, nome, termo_busca, criado_em, modo, url_fixa) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (categoria, nome, termo_busca, _agora(), modo, url_fixa),
    )
    produto_id = cur.lastrowid
    conn.commit()
    conn.close()
    return produto_id


def listar_produtos(categoria=None):
    conn = conectar()
    cur = conn.cursor()
    if categoria:
        cur.execute("SELECT * FROM produtos WHERE categoria = ? ORDER BY nome COLLATE NOCASE", (categoria,))
    else:
        cur.execute("SELECT * FROM produtos ORDER BY categoria, nome COLLATE NOCASE")
    linhas = cur.fetchall()
    conn.close()
    return [dict(l) for l in linhas]


def obter_produto(produto_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    linha = cur.fetchone()
    conn.close()
    return dict(linha) if linha else None


def remover_produto(produto_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Preços / histórico
# --------------------------------------------------------------------------

def registrar_precos(produto_id, resultados):
    """
    resultados: lista de dicts {loja, titulo, preco, url}
    Salva todos como um novo "lote" de busca (mesmo timestamp).
    """
    conn = conectar()
    cur = conn.cursor()
    agora = _agora()
    for r in resultados:
        cur.execute(
            "INSERT INTO precos (produto_id, loja, titulo, preco, url, buscado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (produto_id, r["loja"], r.get("titulo", ""), r["preco"], r.get("url", ""), agora),
        )
    conn.commit()
    conn.close()


def historico_produto(produto_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM precos WHERE produto_id = ? ORDER BY buscado_em DESC, preco ASC",
        (produto_id,),
    )
    linhas = cur.fetchall()
    conn.close()
    return [dict(l) for l in linhas]


def melhor_preco_atual(produto_id):
    """Retorna o registro de menor preço do lote de busca mais recente."""
    hist = historico_produto(produto_id)
    if not hist:
        return None
    ultimo_lote = hist[0]["buscado_em"]
    do_lote = [h for h in hist if h["buscado_em"] == ultimo_lote]
    return min(do_lote, key=lambda h: h["preco"])


def historico_por_url(url):
    """Todo preço já registrado (em qualquer produto) para essa URL exata."""
    if not url:
        return []
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM precos WHERE url = ? ORDER BY buscado_em DESC", (url,))
    linhas = cur.fetchall()
    conn.close()
    return [dict(l) for l in linhas]


def variacao_preco(produto_id):
    """
    Compara o melhor preço do lote de busca mais recente com o melhor preço
    de buscas anteriores.
    Retorna dict: {atual, anterior_min, status, diferenca}
      status: 'verde' (mais barato que antes), 'vermelho' (mais caro que antes),
               'neutro' (igual ou sem histórico anterior)
    """
    hist = historico_produto(produto_id)
    if not hist:
        return None

    lotes = sorted(set(h["buscado_em"] for h in hist), reverse=True)
    if not lotes:
        return None

    ultimo_lote = lotes[0]
    atual_min = min(h["preco"] for h in hist if h["buscado_em"] == ultimo_lote)

    lotes_anteriores = lotes[1:]
    if not lotes_anteriores:
        return {"atual": atual_min, "anterior_min": None, "status": "neutro", "diferenca": 0}

    precos_anteriores = [h["preco"] for h in hist if h["buscado_em"] in lotes_anteriores]
    anterior_min = min(precos_anteriores)

    diff = atual_min - anterior_min
    if diff < -0.01:
        status = "verde"      # ficou mais barato que já esteve
    elif diff > 0.01:
        status = "vermelho"   # ficou mais caro que já esteve
    else:
        status = "neutro"

    return {"atual": atual_min, "anterior_min": anterior_min, "status": status, "diferenca": diff}


# --------------------------------------------------------------------------
# Builds (montagem de PC)
# --------------------------------------------------------------------------

def criar_build(nome):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("INSERT INTO builds (nome, criado_em) VALUES (?, ?)", (nome, _agora()))
    build_id = cur.lastrowid
    conn.commit()
    conn.close()
    return build_id


def listar_builds():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM builds ORDER BY criado_em DESC")
    linhas = cur.fetchall()
    conn.close()
    return [dict(l) for l in linhas]


def obter_build(build_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM builds WHERE id = ?", (build_id,))
    linha = cur.fetchone()
    conn.close()
    return dict(linha) if linha else None


def remover_build(build_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("DELETE FROM builds WHERE id = ?", (build_id,))
    conn.commit()
    conn.close()


def definir_item_build(build_id, categoria, produto_id, loja, titulo, preco, url):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO build_itens (build_id, categoria, produto_id, loja, titulo, preco, url, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(build_id, categoria) DO UPDATE SET
            produto_id=excluded.produto_id,
            loja=excluded.loja,
            titulo=excluded.titulo,
            preco=excluded.preco,
            url=excluded.url,
            atualizado_em=excluded.atualizado_em
    """, (build_id, categoria, produto_id, loja, titulo, preco, url, _agora()))
    conn.commit()
    conn.close()


def remover_item_build(build_id, categoria):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("DELETE FROM build_itens WHERE build_id = ? AND categoria = ?", (build_id, categoria))
    conn.commit()
    conn.close()


def listar_itens_build(build_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM build_itens WHERE build_id = ?", (build_id,))
    linhas = cur.fetchall()
    conn.close()
    return {l["categoria"]: dict(l) for l in linhas}


def registrar_total_build(build_id, total):
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO build_totais (build_id, total, calculado_em) VALUES (?, ?, ?)",
        (build_id, total, _agora()),
    )
    conn.commit()
    conn.close()


def historico_total_build(build_id):
    """Todos os totais já salvos desse PC, do mais antigo pro mais recente."""
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM build_totais WHERE build_id = ? ORDER BY calculado_em ASC",
        (build_id,),
    )
    linhas = cur.fetchall()
    conn.close()
    return [dict(l) for l in linhas]


def variacao_total_build(build_id, total_atual):
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM build_totais WHERE build_id = ? ORDER BY calculado_em DESC",
        (build_id,),
    )
    linhas = [dict(l) for l in cur.fetchall()]
    conn.close()

    if not linhas:
        return {"status": "neutro", "anterior": None, "diferenca": 0}

    anterior_min = min(l["total"] for l in linhas)
    diff = total_atual - anterior_min
    if diff < -0.01:
        status = "verde"
    elif diff > 0.01:
        status = "vermelho"
    else:
        status = "neutro"
    return {"status": status, "anterior": anterior_min, "diferenca": diff}


# --------------------------------------------------------------------------
# Rotinas (checagem automática e agendada de um PC)
# --------------------------------------------------------------------------

def criar_rotina(
    alvo_tipo, horarios, repetir, build_id=None, alvo_categoria=None,
    dias_semana=None, data_unica=None,
    alerta_email=None, alerta_total_abaixo=None, alertar_menor_preco=False,
):
    """
    `alvo_tipo` é 'build' (checa um PC montado — precisa de `build_id`),
    'categoria' (checa todos os produtos de uma categoria — precisa de
    `alvo_categoria`) ou 'tudo' (checa todos os produtos cadastrados, de
    qualquer categoria).

    `horarios` é uma string com um ou mais "HH:MM" separados por vírgula
    (ex.: "09:00,14:00,20:00") — a rotina roda em cada um desses horários.

    `repetir`=True roda todo dia (ou só nos dias de `dias_semana`, ex.:
    "seg,qua,sex" — vazio/None quando repetir=True significa todo dia).
    `repetir`=False roda uma única vez em `data_unica` ("YYYY-MM-DD") e
    depois fica inativa sozinha.

    Se `alerta_email` for passado, manda um e-mail pra esse endereço quando:
    o total do PC ficar abaixo de `alerta_total_abaixo` (só faz sentido com
    `alvo_tipo='build'`), e/ou algum item bater um novo menor preço
    histórico (se `alertar_menor_preco`).
    """
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO rotinas (alvo_tipo, build_id, alvo_categoria, horarios, repetir, dias_semana, "
        "data_unica, ativa, criado_em, alerta_email, alerta_total_abaixo, alertar_menor_preco) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
        (alvo_tipo, build_id, alvo_categoria, horarios, 1 if repetir else 0, dias_semana, data_unica,
         _agora(), alerta_email, alerta_total_abaixo, 1 if alertar_menor_preco else 0),
    )
    rotina_id = cur.lastrowid
    conn.commit()
    conn.close()
    return rotina_id


def listar_rotinas():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("""
        SELECT rotinas.*, builds.nome AS build_nome
        FROM rotinas
        LEFT JOIN builds ON builds.id = rotinas.build_id
        ORDER BY rotinas.horarios
    """)
    linhas = cur.fetchall()
    conn.close()
    return [dict(l) for l in linhas]


def atualizar_rotina(
    rotina_id, alvo_tipo, horarios, repetir, build_id=None, alvo_categoria=None,
    dias_semana=None, data_unica=None,
    alerta_email=None, alerta_total_abaixo=None, alertar_menor_preco=False,
):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("""
        UPDATE rotinas SET
            alvo_tipo = ?, build_id = ?, alvo_categoria = ?, horarios = ?, repetir = ?,
            dias_semana = ?, data_unica = ?,
            alerta_email = ?, alerta_total_abaixo = ?, alertar_menor_preco = ?
        WHERE id = ?
    """, (
        alvo_tipo, build_id, alvo_categoria, horarios, 1 if repetir else 0, dias_semana, data_unica,
        alerta_email, alerta_total_abaixo, 1 if alertar_menor_preco else 0, rotina_id,
    ))
    conn.commit()
    conn.close()


def obter_rotina(rotina_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rotinas WHERE id = ?", (rotina_id,))
    linha = cur.fetchone()
    conn.close()
    return dict(linha) if linha else None


def remover_rotina(rotina_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("DELETE FROM rotinas WHERE id = ?", (rotina_id,))
    conn.commit()
    conn.close()


def definir_rotina_ativa(rotina_id, ativa):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("UPDATE rotinas SET ativa = ? WHERE id = ?", (1 if ativa else 0, rotina_id))
    conn.commit()
    conn.close()


def registrar_execucao_rotina(rotina_id, quando=None, horario=None):
    """`horario` é o "HH:MM" específico (dentre os de `horarios`) que disparou
    essa execução — guardado pra saber se aquele horário específico já rodou
    hoje, já que uma rotina pode ter mais de um horário no mesmo dia."""
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "UPDATE rotinas SET ultima_execucao = ?, ultimo_horario = ? WHERE id = ?",
        (quando or _agora(), horario, rotina_id),
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Exportar / importar dados (produtos, histórico de preços e PCs montados)
# --------------------------------------------------------------------------

FORMATO_EXPORTACAO = "zandonadi-radar-export"
VERSAO_FORMATO_EXPORTACAO = 1


def exportar_dados(categoria=None):
    """
    Devolve um dict pronto pra salvar em JSON com os produtos (e preços
    registrados) de uma categoria, ou de tudo (e, nesse caso, também os
    PCs montados) quando `categoria` é None. Rotinas e credenciais (chave
    da OpenAI, senha de e-mail) nunca entram aqui — são configuração da
    máquina, não dados pra levar de um lugar pro outro.
    """
    conn = conectar()
    cur = conn.cursor()

    if categoria:
        cur.execute("SELECT * FROM produtos WHERE categoria = ?", (categoria,))
    else:
        cur.execute("SELECT * FROM produtos")
    produtos = [dict(l) for l in cur.fetchall()]

    precos = []
    ids_produtos = [p["id"] for p in produtos]
    if ids_produtos:
        marcadores = ",".join("?" * len(ids_produtos))
        cur.execute(f"SELECT * FROM precos WHERE produto_id IN ({marcadores})", ids_produtos)
        precos = [dict(l) for l in cur.fetchall()]

    builds, build_itens, build_totais = [], [], []
    if not categoria:
        cur.execute("SELECT * FROM builds")
        builds = [dict(l) for l in cur.fetchall()]
        cur.execute("SELECT * FROM build_itens")
        build_itens = [dict(l) for l in cur.fetchall()]
        cur.execute("SELECT * FROM build_totais")
        build_totais = [dict(l) for l in cur.fetchall()]

    conn.close()
    return {
        "formato": FORMATO_EXPORTACAO,
        "versao_formato": VERSAO_FORMATO_EXPORTACAO,
        "exportado_em": _agora(),
        "categoria_unica": categoria,
        "produtos": produtos,
        "precos": precos,
        "builds": builds,
        "build_itens": build_itens,
        "build_totais": build_totais,
    }


def importar_dados(dados, substituir=False):
    """
    Importa um dict no formato de `exportar_dados`. `substituir`=True apaga
    TUDO que já existe antes (produtos, preços, PCs montados) — o resultado
    final fica só com o que veio do arquivo. `substituir`=False soma aos
    dados que já existem — cada item do arquivo entra como um produto (ou
    PC) novo, sem mexer no que já estava lá (mesmo que pareça repetido).

    IDs do arquivo não são reaproveitados (evita colidir com IDs que já
    existem no banco) — são remapeados pra novos IDs na hora de inserir.

    Retorna (qtd_produtos_importados, qtd_builds_importados).
    """
    conn = conectar()
    cur = conn.cursor()

    if substituir:
        cur.execute("DELETE FROM builds")
        cur.execute("DELETE FROM produtos")

    mapa_produtos = {}
    for p in dados.get("produtos", []):
        cur.execute(
            "INSERT INTO produtos (categoria, nome, termo_busca, criado_em, modo, url_fixa) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (p["categoria"], p["nome"], p["termo_busca"], p.get("criado_em") or _agora(),
             p.get("modo", "busca"), p.get("url_fixa")),
        )
        mapa_produtos[p["id"]] = cur.lastrowid

    for pr in dados.get("precos", []):
        novo_produto_id = mapa_produtos.get(pr["produto_id"])
        if novo_produto_id is None:
            continue
        cur.execute(
            "INSERT INTO precos (produto_id, loja, titulo, preco, url, buscado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (novo_produto_id, pr["loja"], pr.get("titulo", ""), pr["preco"], pr.get("url", ""), pr["buscado_em"]),
        )

    mapa_builds = {}
    for b in dados.get("builds", []):
        cur.execute(
            "INSERT INTO builds (nome, criado_em) VALUES (?, ?)",
            (b["nome"], b.get("criado_em") or _agora()),
        )
        mapa_builds[b["id"]] = cur.lastrowid

    for bi in dados.get("build_itens", []):
        novo_build_id = mapa_builds.get(bi["build_id"])
        if novo_build_id is None:
            continue
        produto_id_original = bi.get("produto_id")
        novo_produto_id = mapa_produtos.get(produto_id_original) if produto_id_original is not None else None
        cur.execute(
            "INSERT INTO build_itens (build_id, categoria, produto_id, loja, titulo, preco, url, atualizado_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (novo_build_id, bi["categoria"], novo_produto_id, bi.get("loja"), bi.get("titulo"),
             bi.get("preco"), bi.get("url"), bi.get("atualizado_em")),
        )

    for bt in dados.get("build_totais", []):
        novo_build_id = mapa_builds.get(bt["build_id"])
        if novo_build_id is None:
            continue
        cur.execute(
            "INSERT INTO build_totais (build_id, total, calculado_em) VALUES (?, ?, ?)",
            (novo_build_id, bt["total"], bt.get("calculado_em") or _agora()),
        )

    conn.commit()
    conn.close()
    return len(mapa_produtos), len(mapa_builds)
