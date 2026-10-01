# -*- coding: utf-8 -*-
"""
Lógica de rotinas agendadas (checagem automática de preço de um PC inteiro).

De propósito, este módulo NÃO importa Tkinter: além de usado pelo app
principal (botão "Rotinas"), ele também é chamado pelo `rotina_checador.py`
sem nenhuma interface gráfica, via Tarefa Agendada do Windows — precisa
funcionar sozinho, mesmo com o programa fechado.
"""

from datetime import datetime

import database as db
from config import CATEGORIAS, LOJAS_DISPONIVEIS, LOJAS_ELETRO_MOVEIS
from notificacoes import enviar_alerta_email
from scraper import buscar_em_todas_as_lojas, buscar_produto_por_url

DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
NOMES_DIAS = {
    "seg": "Seg", "ter": "Ter", "qua": "Qua", "qui": "Qui",
    "sex": "Sex", "sab": "Sáb", "dom": "Dom",
}


def _formatar_preco(valor):
    texto = f"{valor:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return f"R$ {texto}"


def descricao_alvo(rotina):
    """Texto amigável do que a rotina checa: nome do PC, categoria ou 'tudo'."""
    alvo_tipo = rotina.get("alvo_tipo") or "build"
    if alvo_tipo == "categoria":
        return CATEGORIAS.get(rotina.get("alvo_categoria"), rotina.get("alvo_categoria") or "categoria")
    if alvo_tipo == "tudo":
        return "Tudo o que está cadastrado"
    return rotina.get("build_nome") or "PC removido"


def descricao_horarios(rotina):
    """'09:00' ou '09:00, 14:00, 20:00' — texto amigável dos horários da rotina."""
    horarios = [h.strip() for h in (rotina.get("horarios") or "").split(",") if h.strip()]
    return ", ".join(sorted(horarios)) if horarios else "—"


def descricao_recorrencia(rotina):
    """Texto amigável pra mostrar na lista de rotinas: 'todo dia', 'Seg, Qua, Sex', 'uma vez em 20/09/2026'."""
    if not rotina.get("repetir"):
        data_unica = rotina.get("data_unica")
        if data_unica:
            try:
                d = datetime.strptime(data_unica, "%Y-%m-%d")
                return f"uma vez em {d.strftime('%d/%m/%Y')}"
            except ValueError:
                pass
        return "uma vez"

    dias = [d for d in (rotina.get("dias_semana") or "").split(",") if d]
    if not dias:
        return "todo dia"
    return ", ".join(NOMES_DIAS[d] for d in DIAS_SEMANA if d in dias)


def horario_pendente(rotina, agora=None, janela_minutos=20):
    """
    Devolve qual "HH:MM" (dentre os de `rotina["horarios"]`) deveria rodar
    agora, ou None se nenhum está pendente: a rotina precisa estar ativa, o
    dia precisa bater (dia da semana certo, data única certa, ou "todo dia"
    quando não restringe nenhum dia), aquele horário específico ainda não
    pode ter rodado hoje, e o horário atual precisa estar dentro da janela
    de tolerância logo depois do horário marcado.

    A janela existe porque quem chama isso (a Tarefa Agendada) roda a cada
    ~15 minutos, não no segundo exato — sem essa margem a rotina podia
    "passar batido" do horário marcado. Uma rotina pode ter vários horários
    no mesmo dia (ex.: "09:00,14:00,20:00") — cada um é checado e marcado
    como já rodado separadamente, pra um não bloquear o outro.
    """
    if not rotina.get("ativa"):
        return None

    agora = agora or datetime.now()

    if not rotina.get("repetir"):
        data_unica = rotina.get("data_unica")
        if not data_unica:
            return None
        try:
            data_alvo = datetime.strptime(data_unica, "%Y-%m-%d").date()
        except ValueError:
            return None
        if agora.date() != data_alvo:
            return None
    else:
        dias = [d for d in (rotina.get("dias_semana") or "").split(",") if d]
        if dias and DIAS_SEMANA[agora.weekday()] not in dias:
            return None

    ultima_execucao = rotina.get("ultima_execucao")
    ultima_data = None
    if ultima_execucao:
        try:
            ultima_data = datetime.strptime(ultima_execucao, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            pass

    horarios = [h.strip() for h in (rotina.get("horarios") or "").split(",") if h.strip()]
    for horario in horarios:
        try:
            h, m = map(int, horario.split(":"))
        except ValueError:
            continue
        agendado = agora.replace(hour=h, minute=m, second=0, microsecond=0)
        delta_minutos = (agora - agendado).total_seconds() / 60
        if not (0 <= delta_minutos < janela_minutos):
            continue
        if ultima_data == agora.date() and rotina.get("ultimo_horario") == horario:
            continue  # esse horário específico já rodou hoje
        return horario

    return None


def rotina_esta_devida(rotina, agora=None, janela_minutos=20):
    """True se algum horário da rotina está pendente agora. Ver `horario_pendente`."""
    return horario_pendente(rotina, agora, janela_minutos) is not None


def _buscar_preco_produto(produto):
    """Mesma lógica usada em qualquer outro lugar do app pra atualizar o
    preço de um produto já cadastrado: segue o link fixo se foi cadastrado
    por link, ou busca o termo de novo nas lojas certas pra categoria dele."""
    if produto.get("modo") == "url" and produto.get("url_fixa"):
        return buscar_produto_por_url(produto["url_fixa"])
    lojas = LOJAS_ELETRO_MOVEIS if produto.get("categoria") == "eletrodomesticos_moveis" else LOJAS_DISPONIVEIS
    return buscar_em_todas_as_lojas(produto["termo_busca"], lojas=lojas)


def _checar_novo_recorde(produto, novos_recordes):
    variacao = db.variacao_preco(produto["id"])
    if variacao and variacao["status"] == "verde" and variacao.get("anterior_min") is not None:
        novos_recordes.append((produto["nome"], variacao["atual"], variacao["anterior_min"]))


def executar_rotina(rotina, callback_progresso=None, log_fn=None, horario=None):
    """
    Busca de novo o preço de cada item do alvo dessa rotina — um PC montado
    inteiro (mesma lógica do botão "Recalcular preços de todas as peças"),
    todos os produtos de uma categoria, ou todos os produtos cadastrados —
    salva o histórico, dispara o alerta por e-mail se as condições baterem,
    e marca a rotina como executada agora. Retorna False se o alvo da
    rotina não existir mais (ex.: o PC foi excluído).

    `callback_progresso(nome_item)`, se passado, é chamado antes de buscar
    cada item (útil pra mostrar progresso na interface).

    `log_fn(mensagem)`, se passado, recebe avisos de acompanhamento (ex.: se
    o e-mail de alerta foi enviado ou falhou) — quem chama decide o que
    fazer com isso (gravar num log, mostrar na tela etc.).

    `horario`, se passado, é o "HH:MM" específico que disparou essa
    execução (de `horario_pendente`) — guardado pra esse horário em
    particular não rodar de novo hoje, mesmo que a rotina tenha outros
    horários no mesmo dia.
    """
    log_fn = log_fn or (lambda mensagem: None)
    alvo_tipo = rotina.get("alvo_tipo") or "build"
    novos_recordes = []  # [(nome_item, preco_novo, preco_anterior), ...]
    total = None

    if alvo_tipo == "build":
        build = db.obter_build(rotina["build_id"])
        if not build:
            return False
        alvo_nome = build["nome"]

        itens = db.listar_itens_build(build["id"])
        for categoria_chave, item in itens.items():
            if not item.get("produto_id"):
                continue
            produto = db.obter_produto(item["produto_id"])
            if not produto:
                continue

            if callback_progresso:
                callback_progresso(produto["nome"])

            resultados = _buscar_preco_produto(produto)
            if resultados:
                db.registrar_precos(produto["id"], resultados)
                melhor = min(resultados, key=lambda r: r["preco"])
                db.definir_item_build(
                    build["id"], categoria_chave, produto["id"],
                    melhor.get("loja"), melhor.get("titulo") or produto["nome"],
                    melhor["preco"], melhor.get("url", "")
                )
                if rotina.get("alertar_menor_preco"):
                    _checar_novo_recorde(produto, novos_recordes)

        itens_atualizados = db.listar_itens_build(build["id"])
        preenchidos = [i for i in itens_atualizados.values() if i.get("preco")]
        total = sum(i["preco"] for i in preenchidos) if preenchidos else None
        if total is not None:
            db.registrar_total_build(build["id"], total)

    else:
        if alvo_tipo == "categoria":
            categoria_chave = rotina.get("alvo_categoria")
            produtos = db.listar_produtos(categoria_chave)
            alvo_nome = CATEGORIAS.get(categoria_chave, categoria_chave or "categoria")
        else:  # "tudo"
            produtos = db.listar_produtos()
            alvo_nome = "tudo o que está cadastrado"

        for produto in produtos:
            if callback_progresso:
                callback_progresso(produto["nome"])

            resultados = _buscar_preco_produto(produto)
            if resultados:
                db.registrar_precos(produto["id"], resultados)
                if rotina.get("alertar_menor_preco"):
                    _checar_novo_recorde(produto, novos_recordes)

    db.registrar_execucao_rotina(rotina["id"], horario=horario or datetime.now().strftime("%H:%M"))
    if not rotina.get("repetir"):
        db.definir_rotina_ativa(rotina["id"], False)

    _enviar_alerta_se_necessario(rotina, alvo_nome, total, novos_recordes, log_fn)
    return True


def _enviar_alerta_se_necessario(rotina, alvo_nome, total, novos_recordes, log_fn):
    destino = rotina.get("alerta_email")
    if not destino:
        return

    motivos = []
    limite = rotina.get("alerta_total_abaixo")
    if limite and total is not None and total < limite:
        motivos.append(
            f"O total de “{alvo_nome}” caiu para {_formatar_preco(total)} "
            f"(abaixo do limite de {_formatar_preco(limite)})."
        )
    for nome, novo, anterior in novos_recordes:
        motivos.append(
            f"“{nome}” bateu um novo menor preço: {_formatar_preco(novo)} "
            f"(antes: {_formatar_preco(anterior)})."
        )

    if not motivos:
        return

    assunto = f"💰 Alerta de preço — {alvo_nome}"
    corpo = (
        "\n".join(motivos)
        + f"\n\nChecado em {datetime.now().strftime('%d/%m/%Y %H:%M')} pelo Zandonadi Radar."
    )
    ok, erro = enviar_alerta_email(destino, assunto, corpo)
    if ok:
        log_fn(f"Alerta de preço enviado por e-mail para {destino}.")
    else:
        log_fn(f"Não consegui enviar o alerta por e-mail: {erro}")
