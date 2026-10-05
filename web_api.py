# -*- coding: utf-8 -*-
"""
Ponte Python <-> JavaScript pro front-end novo (PyWebView). Os métodos desta
classe ficam expostos em `window.pywebview.api.<metodo>(...)` no JS. Nada de
lógica de negócio mora aqui -- só traduz pra/de JSON e chama os mesmos
módulos de sempre (database, scraper, llm, rotinas, notificacoes).

Operações rápidas (listar, remover) devolvem o resultado direto. Operações
demoradas (buscar nas lojas) disparam uma thread e avisam o JS via
`window.evaluate_js(...)` quando têm progresso/resultado -- é o mesmo
padrão de "fila de eventos" que o main.py em Tkinter já usava, só que o
"evento" agora é uma chamada de função JS em vez de botar na fila.
"""

import json
import os
import subprocess
import threading
import time
import webbrowser
from datetime import datetime

import webview

import atualizacoes
import compatibilidade
import database as db
import llm
import notificacoes
import rotinas as rotinas_mod
from config import (
    CATEGORIAS, LOJAS_DISPONIVEIS, LOJAS_ELETRO_MOVEIS, ORDEM_CATEGORIAS, ORDEM_CATEGORIAS_CASA,
    VERSAO_APP,
)
from scraper import buscar_em_todas_as_lojas, buscar_produto_por_url
from tarefas_agendadas import garantir_tarefa_agendada, remover_tarefa_agendada, tarefa_agendada_existe


def _variacao_resumo(produto_id):
    """Mesmo cálculo que _linha_produto fazia no Tkinter: melhor preço atual
    + status verde/vermelho/neutro + variação percentual."""
    melhor = db.melhor_preco_atual(produto_id)
    if not melhor:
        return None
    variacao = db.variacao_preco(produto_id)
    percentual = None
    if variacao and variacao.get("anterior_min"):
        percentual = round(abs(variacao["diferenca"]) / variacao["anterior_min"] * 100)
    return {
        "preco": melhor["preco"],
        "loja": melhor["loja"],
        "titulo": melhor.get("titulo"),
        "status": variacao["status"] if variacao else "neutro",
        "percentual": percentual,
    }


def _status_preco_resultado(resultado):
    """'verde' se esse preço é o mais barato já visto pra essa URL exata, 'vermelho' se é
    o mais caro, 'neutro' se é a primeira vez (ou empatou)."""
    hist = db.historico_por_url(resultado.get("url"))
    if not hist:
        return "neutro"
    anteriores = [h["preco"] for h in hist]
    if resultado["preco"] < min(anteriores) - 0.01:
        return "verde"
    if resultado["preco"] > max(anteriores) + 0.01:
        return "vermelho"
    return "neutro"


def _lojas_para_categoria(categoria):
    return LOJAS_ELETRO_MOVEIS if categoria == "eletrodomesticos_moveis" else LOJAS_DISPONIVEIS


class API:
    def __init__(self):
        # Nome com "_" de propósito: o pywebview introspecciona todo atributo
        # público do js_api pra expor sub-objetos em JS, e recursaria pra
        # dentro do controle nativo da janela (WinForms/.NET), estourando o
        # limite de recursão do Python e derrubando a ponte inteira antes de
        # expor qualquer método. Prefixo "_" faz o pywebview pular o atributo.
        self._window = None  # preenchido depois que a janela é criada (ver main_web.py)
        self._importacao_pendente = None  # dados lidos em escolher_arquivo_importacao, até confirmar_importacao
        self._busca_evento = None  # threading.Event da busca em andamento (pra "Parar")
        self._busca_resultados = []  # última busca concluída, pra "Adicionar" referenciar por índice
        self._busca_termo = ""
        self._link_item = None  # produto lido em verificar_link, até adicionar_por_link
        self._atualizacao_info = None  # release lida em verificar_atualizacao, até instalar_atualizacao
        self._rotinas_em_execucao = set()
        self._rotinas_lock = threading.Lock()

    def _emit(self, nome_funcao_js, dados):
        if self._window:
            self._window.evaluate_js(f"{nome_funcao_js}({json.dumps(dados, ensure_ascii=False)})")

    # ------------------------------------------------------------------
    # Categorias / listagem
    # ------------------------------------------------------------------
    def listar_categorias(self):
        return {
            "pc": [{"chave": c, "rotulo": CATEGORIAS[c]} for c in ORDEM_CATEGORIAS],
            "casa": [{"chave": c, "rotulo": CATEGORIAS[c]} for c in ORDEM_CATEGORIAS_CASA],
        }

    def versao_app(self):
        return VERSAO_APP

    def listar_produtos(self, categoria):
        produtos = db.listar_produtos(categoria)
        return [
            {
                "id": p["id"],
                "nome": p["nome"],
                "modo": p["modo"],
                "url_fixa": p.get("url_fixa"),
                "alerta_queda_percentual": p.get("alerta_queda_percentual"),
                "resumo": _variacao_resumo(p["id"]),
            }
            for p in produtos
        ]

    def remover_produto(self, produto_id):
        db.remover_produto(produto_id)
        return True

    def obter_historico(self, produto_id):
        produto = db.obter_produto(produto_id)
        if not produto:
            return None
        return {"produto": produto, "historico": db.historico_produto(produto_id)}

    def definir_alerta_produto(self, produto_id, percentual):
        """`percentual` None desliga o alerta. Mesma validação do diálogo Tkinter."""
        if percentual is None:
            db.definir_alerta_queda_produto(produto_id, None)
            return {"ok": True, "aviso": None}
        try:
            percentual = float(str(percentual).replace(",", "."))
            if percentual <= 0:
                raise ValueError
        except ValueError:
            return {"ok": False, "erro": "Digite um número maior que 0 (ex.: 10)."}
        db.definir_alerta_queda_produto(produto_id, percentual)
        aviso = None
        if not db.obter_configuracao("email_alerta_padrao"):
            aviso = "Salvo, mas configure um e-mail padrão em Configurações pra esse alerta poder sair de verdade."
        return {"ok": True, "aviso": aviso}

    def abrir_url(self, url):
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            webbrowser.open(url)
            return True
        return False

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------
    def buscar(self, termo, categoria, pular_sugestao=False):
        """Se a IA estiver configurada, antes de gastar tempo nas lojas ela confere se dá
        pra sugerir um termo mais objetivo -- só interrompe se achar algo melhor de verdade
        (avisa o JS via onSugestaoBusca; ele chama de novo com pular_sugestao=True)."""
        termo = (termo or "").strip()
        if not termo:
            return {"ok": False, "erro": "Digite o que você quer buscar."}
        if self._busca_evento is not None:
            self._busca_evento.set()  # cancela uma busca anterior ainda rodando
        evento = threading.Event()
        self._busca_evento = evento
        threading.Thread(
            target=self._trabalho_busca, args=(termo, categoria, pular_sugestao, evento), daemon=True
        ).start()
        return {"ok": True}

    def _trabalho_busca(self, termo, categoria, pular_sugestao, evento):
        if not pular_sugestao and llm.esta_configurado():
            self._emit("onProgressoBusca", {"loja": "Assistente", "status": "pensando num termo melhor..."})
            try:
                sugestao = llm.sugerir_melhoria_termo_llm(termo)
            except Exception:
                sugestao = None
            if evento.is_set():
                return
            if sugestao:
                self._emit("onSugestaoBusca", {"termo": termo, "sugestao": sugestao, "categoria": categoria})
                return

        def progresso(loja, status):
            if not evento.is_set():
                self._emit("onProgressoBusca", {"loja": loja, "status": status})

        try:
            resultados = buscar_em_todas_as_lojas(
                termo, lojas=_lojas_para_categoria(categoria), callback_progresso=progresso,
                cancelar_evento=evento,
            )
        except Exception as e:
            if not evento.is_set():
                self._emit("onBuscaErro", {"mensagem": str(e)})
            return
        if evento.is_set():
            return  # foi cancelada (Parar) ou substituída por outra busca
        self._busca_resultados = resultados
        self._busca_termo = termo
        self._emit("onBuscaConcluida", {
            "termo": termo,
            "resultados": [dict(r, status_preco=_status_preco_resultado(r)) for r in resultados],
        })

    def parar_busca(self):
        if self._busca_evento is not None:
            self._busca_evento.set()
            self._busca_evento = None
        return True

    def adicionar_selecionados(self, categoria, indices):
        """Cada resultado marcado vira um produto separado, fixo no link dele."""
        nomes = []
        for i in indices:
            if not (0 <= i < len(self._busca_resultados)):
                continue
            item = self._busca_resultados[i]
            nome = item["titulo"][:80]
            produto_id = db.adicionar_produto(categoria, nome, item["url"], modo="url", url_fixa=item["url"])
            db.registrar_precos(produto_id, [item])
            nomes.append(nome)
        return {"ok": bool(nomes), "nomes": nomes}

    def adicionar_tudo_como_produto(self, categoria, nome):
        """Todos os resultados da busca viram UM produto (que será rebuscado pelo termo)."""
        nome = (nome or "").strip()
        if not self._busca_resultados:
            return {"ok": False, "erro": "Não há resultados pra adicionar."}
        if not nome:
            return {"ok": False, "erro": "Dê um nome pra esse item."}
        produto_id = db.adicionar_produto(categoria, nome, self._busca_termo)
        db.registrar_precos(produto_id, self._busca_resultados)
        return {"ok": True, "nome": nome, "qtd": len(self._busca_resultados)}

    # ------------------------------------------------------------------
    # Adicionar produto por link direto
    # ------------------------------------------------------------------
    def verificar_link(self, url):
        url = (url or "").strip()
        if not url:
            return {"ok": False, "erro": "Cole o link do produto."}
        if not url.startswith("http"):
            return {"ok": False, "erro": "Isso não parece um link válido."}
        self._link_item = None
        threading.Thread(target=self._trabalho_verificar_link, args=(url,), daemon=True).start()
        return {"ok": True}

    def _trabalho_verificar_link(self, url):
        def progresso(loja, status):
            self._emit("onProgressoLink", {"loja": loja, "status": status})

        try:
            resultados = buscar_produto_por_url(url, callback_progresso=progresso)
        except Exception:
            resultados = []
        if not resultados:
            self._emit("onLinkVerificado", {"ok": False})
            return
        self._link_item = resultados[0]
        self._emit("onLinkVerificado", {"ok": True, "item": self._link_item})

    def adicionar_por_link(self, categoria, nome):
        item = self._link_item
        if not item:
            return {"ok": False, "erro": "Verifique o link primeiro."}
        nome = (nome or "").strip() or item["titulo"]
        produto_id = db.adicionar_produto(categoria, nome, item["url"], modo="url", url_fixa=item["url"])
        db.registrar_precos(produto_id, [item])
        self._link_item = None
        return {"ok": True, "nome": nome}

    def atualizar_preco_produto(self, produto_id):
        threading.Thread(target=self._trabalho_atualizar, args=(produto_id,), daemon=True).start()
        return True

    def _trabalho_atualizar(self, produto_id):
        produto = db.obter_produto(produto_id)
        if not produto:
            self._emit("onPrecoAtualizado", {"produto_id": produto_id, "ok": False})
            return

        if produto.get("modo") == "url" and produto.get("url_fixa"):
            resultados = buscar_produto_por_url(produto["url_fixa"])
        else:
            resultados = buscar_em_todas_as_lojas(
                produto["termo_busca"], lojas=_lojas_para_categoria(produto["categoria"])
            )

        if resultados:
            db.registrar_precos(produto["id"], resultados)
            notificacoes.verificar_e_alertar_queda_produto(produto["id"])

        self._emit("onPrecoAtualizado", {
            "produto_id": produto_id, "ok": bool(resultados), "resumo": _variacao_resumo(produto_id),
        })

    # ------------------------------------------------------------------
    # Montar PC (builds)
    # ------------------------------------------------------------------
    def listar_builds(self):
        return [{"id": b["id"], "nome": b["nome"]} for b in db.listar_builds()]

    def criar_build(self, nome):
        return db.criar_build(nome)

    def remover_build(self, build_id):
        db.remover_build(build_id)
        return True

    def obter_build_completo(self, build_id):
        build = db.obter_build(build_id)
        if not build:
            return None
        itens = db.listar_itens_build(build_id)
        slots = []
        preenchidos = []
        for categoria in ORDEM_CATEGORIAS:
            item = itens.get(categoria)
            tem_peca = bool(item and item.get("produto_id"))
            slots.append({
                "categoria": categoria,
                "rotulo": CATEGORIAS[categoria],
                "preenchido": tem_peca,
                "item": {
                    "titulo": item["titulo"], "preco": item["preco"], "loja": item["loja"],
                } if tem_peca else None,
            })
            if tem_peca:
                preenchidos.append(item)

        total = sum(i["preco"] for i in preenchidos)
        variacao = db.variacao_total_build(build_id, total) if preenchidos else None
        return {
            "build": {"id": build["id"], "nome": build["nome"]},
            "slots": slots,
            "total": total,
            "preenchidos": len(preenchidos),
            "total_slots": len(ORDEM_CATEGORIAS),
            "variacao": variacao,
        }

    def obter_grafico_build(self, build_id):
        """Dados do botão "Gráfico" do PC: evolução do total salvo (com "Finalizar")
        + quanto cada peça variou desde a busca anterior. Mesma lógica do Tkinter."""
        build = db.obter_build(build_id)
        if not build:
            return None

        totais = []
        for t in db.historico_total_build(build_id):
            # Vários "Finalizar" seguidos sem o preço mudar geram totais repetidos -- junta.
            if totais and abs(totais[-1]["total"] - t["total"]) < 0.01:
                continue
            totais.append({"data": t["calculado_em"], "total": t["total"]})

        itens = db.listar_itens_build(build_id)
        pecas = []
        for categoria in ORDEM_CATEGORIAS:
            item = itens.get(categoria)
            if not item or not item.get("produto_id"):
                continue
            variacao = db.variacao_preco(item["produto_id"])
            if not variacao or variacao.get("anterior_min") is None:
                continue
            pecas.append({
                "rotulo": f"{CATEGORIAS[categoria]} — {(item.get('titulo') or '')[:28]}",
                "diferenca": variacao["diferenca"],
                "status": variacao["status"],
            })
        pecas.sort(key=lambda p: p["diferenca"])
        return {"nome": build["nome"], "totais": totais, "pecas": pecas}

    def remover_peca_slot(self, build_id, categoria):
        db.remover_item_build(build_id, categoria)
        return True

    def listar_produtos_para_slot(self, categoria):
        return [{"id": p["id"], "nome": p["nome"]} for p in db.listar_produtos(categoria)]

    def selecionar_peca_slot(self, build_id, categoria, produto_id):
        threading.Thread(
            target=self._trabalho_selecionar_peca, args=(build_id, categoria, produto_id), daemon=True,
        ).start()
        return True

    def _trabalho_selecionar_peca(self, build_id, categoria, produto_id):
        produto = db.obter_produto(produto_id)
        if not produto:
            self._emit("onPecaSelecionada", {"build_id": build_id, "ok": False})
            return

        if produto.get("modo") == "url" and produto.get("url_fixa"):
            resultados = buscar_produto_por_url(produto["url_fixa"])
        else:
            resultados = buscar_em_todas_as_lojas(produto["termo_busca"], lojas=_lojas_para_categoria(categoria))

        if resultados:
            db.registrar_precos(produto["id"], resultados)
            notificacoes.verificar_e_alertar_queda_produto(produto["id"])
            melhor = min(resultados, key=lambda r: r["preco"])
        else:
            melhor = db.melhor_preco_atual(produto["id"])

        if melhor:
            db.definir_item_build(
                build_id, categoria, produto["id"],
                melhor.get("loja"), melhor.get("titulo") or produto["nome"],
                melhor["preco"], melhor.get("url", ""),
            )
        self._emit("onPecaSelecionada", {"build_id": build_id, "ok": bool(melhor)})

    def recalcular_precos_build(self, build_id):
        threading.Thread(target=self._trabalho_recalcular_build, args=(build_id,), daemon=True).start()
        return True

    def _trabalho_recalcular_build(self, build_id):
        itens = db.listar_itens_build(build_id)
        alvos = [(cat, item) for cat, item in itens.items() if item.get("produto_id")]

        for i, (categoria, item) in enumerate(alvos, start=1):
            produto = db.obter_produto(item["produto_id"])
            if not produto:
                continue
            self._emit("onProgressoRecalculo", {
                "build_id": build_id, "atual": i, "total": len(alvos), "nome": produto["nome"],
            })
            if produto.get("modo") == "url" and produto.get("url_fixa"):
                resultados = buscar_produto_por_url(produto["url_fixa"])
            else:
                resultados = buscar_em_todas_as_lojas(
                    produto["termo_busca"], lojas=_lojas_para_categoria(categoria)
                )
            if resultados:
                db.registrar_precos(produto["id"], resultados)
                notificacoes.verificar_e_alertar_queda_produto(produto["id"])
                melhor = min(resultados, key=lambda r: r["preco"])
                db.definir_item_build(
                    build_id, categoria, produto["id"],
                    melhor.get("loja"), melhor.get("titulo") or produto["nome"],
                    melhor["preco"], melhor.get("url", ""),
                )

        self._emit("onRecalculoConcluido", {"build_id": build_id})

    def finalizar_build(self, build_id, total):
        db.registrar_total_build(build_id, total)
        return True

    def checar_compatibilidade_build(self, build_id):
        itens = db.listar_itens_build(build_id)
        preenchidos = [i for i in itens.values() if i.get("produto_id")]
        if len(preenchidos) < 2 or not llm.esta_configurado():
            self._emit("onCompatibilidadeResultado", {"build_id": build_id, "aplica": False, "avisos": []})
            return True
        threading.Thread(target=self._trabalho_compat, args=(build_id, itens), daemon=True).start()
        return True

    def _trabalho_compat(self, build_id, itens):
        try:
            avisos = compatibilidade.checar_build(itens)
        except Exception:
            avisos = []
        self._emit("onCompatibilidadeResultado", {"build_id": build_id, "aplica": True, "avisos": avisos})

    # ------------------------------------------------------------------
    # Rotinas
    # ------------------------------------------------------------------
    def tarefa_agendada_status(self):
        return tarefa_agendada_existe()

    def listar_rotinas(self):
        resultado = []
        for r in db.listar_rotinas():
            resultado.append({
                "id": r["id"],
                "alvo_tipo": r.get("alvo_tipo") or "build",
                "build_id": r.get("build_id"),
                "alvo_categoria": r.get("alvo_categoria"),
                "horarios": [h for h in (r.get("horarios") or "").split(",") if h],
                "repetir": bool(r.get("repetir")),
                "dias_semana": [d for d in (r.get("dias_semana") or "").split(",") if d],
                "data_unica": r.get("data_unica"),
                "ativa": bool(r.get("ativa")),
                "ultima_execucao": r.get("ultima_execucao"),
                "alerta_email": r.get("alerta_email"),
                "alerta_total_abaixo": r.get("alerta_total_abaixo"),
                "alertar_menor_preco": bool(r.get("alertar_menor_preco")),
                "descricao_alvo": rotinas_mod.descricao_alvo(r),
                "descricao_recorrencia": rotinas_mod.descricao_recorrencia(r),
                "descricao_horarios": rotinas_mod.descricao_horarios(r),
            })
        return resultado

    def salvar_rotina(self, dados):
        """`dados` vem do formulário JS (ver abrirDialogoRotina em index.html).
        Mesma validação do antigo diálogo Tkinter (_rotina_dialog)."""
        alvo_tipo = dados.get("alvo_tipo")
        build_id = None
        alvo_categoria = None

        if alvo_tipo == "build":
            build_id = dados.get("build_id")
            if not build_id:
                return {"ok": False, "erro": 'Escolha um PC (ou crie um em "Montar PC" antes).'}
        elif alvo_tipo == "categoria":
            alvo_categoria = dados.get("alvo_categoria")
            if not alvo_categoria:
                return {"ok": False, "erro": "Escolha uma categoria."}

        horarios_lista = dados.get("horarios") or []
        if not horarios_lista:
            return {"ok": False, "erro": "Adicione pelo menos um horário."}
        horarios_final = ",".join(sorted(set(horarios_lista)))

        tipo = dados.get("tipo_repeticao")

        alerta_email = None
        alerta_total_abaixo = None
        alertar_menor_preco = False
        if dados.get("alerta_ativo"):
            alerta_email = (dados.get("alerta_email") or "").strip()
            if not alerta_email or "@" not in alerta_email:
                return {"ok": False, "erro": "Digite um e-mail válido pra receber o alerta."}
            if alvo_tipo == "build" and dados.get("alerta_total_ativo"):
                try:
                    alerta_total_abaixo = float(str(dados.get("alerta_total_valor") or "").strip().replace(",", "."))
                except ValueError:
                    return {"ok": False, "erro": "Digite um valor numérico pro limite do total (ex.: 4500)."}
            alertar_menor_preco = bool(dados.get("alertar_menor_preco"))

        if tipo == "unica":
            texto_data = (dados.get("data_unica") or "").strip()
            try:
                data_obj = datetime.strptime(texto_data, "%d/%m/%Y")
            except ValueError:
                return {"ok": False, "erro": "Use o formato DD/MM/AAAA pra data."}
            repetir_final, dias_final, data_final = False, None, data_obj.strftime("%Y-%m-%d")
        else:
            dias_selecionados = (dados.get("dias_semana") or []) if tipo == "dias" else []
            if tipo == "dias" and not dias_selecionados:
                return {"ok": False, "erro": "Escolha pelo menos um dia da semana."}
            repetir_final, dias_final, data_final = True, ",".join(dias_selecionados) or None, None

        rotina_id = dados.get("id")
        if rotina_id:
            db.atualizar_rotina(
                rotina_id, alvo_tipo, horarios_final, repetir=repetir_final,
                build_id=build_id, alvo_categoria=alvo_categoria,
                dias_semana=dias_final, data_unica=data_final, alerta_email=alerta_email,
                alerta_total_abaixo=alerta_total_abaixo, alertar_menor_preco=alertar_menor_preco,
            )
        else:
            db.criar_rotina(
                alvo_tipo, horarios_final, repetir=repetir_final,
                build_id=build_id, alvo_categoria=alvo_categoria,
                dias_semana=dias_final, data_unica=data_final,
                alerta_email=alerta_email, alerta_total_abaixo=alerta_total_abaixo,
                alertar_menor_preco=alertar_menor_preco,
            )

        avisos = []
        if not garantir_tarefa_agendada():
            avisos.append(
                "Não consegui criar a tarefa agendada do Windows agora. Ela ainda roda sozinha enquanto "
                "o app estiver aberto -- pra rodar também com o app fechado, tente de novo mais tarde."
            )
        if alerta_email and not notificacoes.remetente_configurado():
            avisos.append(
                "O alerta por e-mail está ativado, mas o remetente ainda não foi configurado "
                "(email_config.py)."
            )
        return {"ok": True, "avisos": avisos}

    def alternar_rotina(self, rotina_id, ativa):
        db.definir_rotina_ativa(rotina_id, ativa)
        return True

    def remover_rotina(self, rotina_id):
        db.remover_rotina(rotina_id)
        if not db.listar_rotinas():
            remover_tarefa_agendada()
        return True

    def rodar_rotina_agora(self, rotina_id):
        rotina = db.obter_rotina(rotina_id)
        if not rotina:
            self._emit("onRotinaErro", {"rotina_id": rotina_id, "mensagem": "Rotina não encontrada."})
            return True
        if rotina.get("alvo_tipo", "build") == "build" and not db.obter_build(rotina["build_id"]):
            self._emit("onRotinaErro", {"rotina_id": rotina_id, "mensagem": "O PC dessa rotina não existe mais."})
            return True
        threading.Thread(target=self._trabalho_rodar_rotina, args=(rotina,), daemon=True).start()
        return True

    def _trabalho_rodar_rotina(self, rotina):
        def progresso(nome_peca):
            self._emit("onProgressoRotina", {"rotina_id": rotina["id"], "nome": nome_peca})

        with self._rotinas_lock:
            if rotina["id"] in self._rotinas_em_execucao:
                self._emit("onRotinaErro", {"rotina_id": rotina["id"], "mensagem": "Essa rotina já está rodando."})
                return
            self._rotinas_em_execucao.add(rotina["id"])
        avisos = []
        try:
            rotinas_mod.executar_rotina(rotina, callback_progresso=progresso, log_fn=avisos.append)
        finally:
            with self._rotinas_lock:
                self._rotinas_em_execucao.discard(rotina["id"])
        self._emit("onRotinaConcluida", {"rotina_id": rotina["id"], "avisos": avisos})

    def _loop_rotinas_em_segundo_plano(self):
        """Reforço além da Tarefa Agendada do Windows: enquanto o app estiver aberto, confere
        a cada minuto se alguma rotina está na hora de rodar. Silencioso. Roda numa thread
        iniciada por main_web.py (webview.start)."""
        time.sleep(5)
        while True:
            try:
                agora = datetime.now()
                for rotina in db.listar_rotinas():
                    with self._rotinas_lock:
                        if rotina["id"] in self._rotinas_em_execucao:
                            continue
                    horario = rotinas_mod.horario_pendente(rotina, agora)
                    if horario is not None:
                        with self._rotinas_lock:
                            self._rotinas_em_execucao.add(rotina["id"])
                        threading.Thread(
                            target=self._rodar_rotina_silenciosa, args=(rotina, horario), daemon=True
                        ).start()
            except Exception:
                pass
            time.sleep(60)

    def _rodar_rotina_silenciosa(self, rotina, horario):
        try:
            rotinas_mod.executar_rotina(rotina, horario=horario)
        finally:
            with self._rotinas_lock:
                self._rotinas_em_execucao.discard(rotina["id"])
            self._emit("onRotinasAtualizadas", {})

    # ------------------------------------------------------------------
    # Atualização automática (GitHub Releases -- ver atualizacoes.py)
    # ------------------------------------------------------------------
    def verificar_atualizacao(self):
        """Silencioso: devolve None se não tem versão nova, não tem internet etc."""
        info = atualizacoes.verificar_atualizacao()
        self._atualizacao_info = info
        if not info:
            return None
        return {"versao": info["versao"], "notas": info["notas"][:600], "versao_atual": VERSAO_APP}

    def instalar_atualizacao(self):
        # A URL vem sempre do que verificar_atualizacao() guardou aqui (nunca do JS):
        # esse método baixa e EXECUTA um instalador.
        if not self._atualizacao_info:
            return False
        threading.Thread(target=self._trabalho_instalar_atualizacao, daemon=True).start()
        return True

    def _trabalho_instalar_atualizacao(self):
        info = self._atualizacao_info

        def progresso(pct):
            self._emit("onProgressoAtualizacao", {"pct": pct})

        caminho = atualizacoes.baixar_instalador(info["url_instalador"], callback_progresso=progresso)
        if not caminho:
            self._emit("onFalhaAtualizacao", {
                "mensagem": "Não consegui baixar a atualização agora.", "url_release": info["url_release"],
            })
            return
        try:
            subprocess.Popen([caminho])
        except Exception as e:
            self._emit("onFalhaAtualizacao", {"mensagem": f"Erro ao abrir o instalador: {e}", "url_release": info["url_release"]})
            return
        os._exit(0)

    # ------------------------------------------------------------------
    # Configurações
    # ------------------------------------------------------------------
    def obter_email_alerta(self):
        return db.obter_configuracao("email_alerta_padrao", "")

    def definir_email_alerta(self, email):
        email = (email or "").strip()
        if email and "@" not in email:
            return {"ok": False, "erro": "Digite um e-mail válido (ou deixe em branco)."}
        db.definir_configuracao("email_alerta_padrao", email)
        aviso = None
        if email and not notificacoes.remetente_configurado():
            aviso = (
                "E-mail salvo! Mas o remetente ainda não está configurado -- preencha email_config.py "
                "(SMTP_EMAIL e SMTP_SENHA_APP) pra os alertas saírem de verdade."
            )
        return {"ok": True, "aviso": aviso}

    def listar_opcoes_exportacao(self):
        opcoes = [{"chave": "__tudo__", "rotulo": "Tudo (todos os produtos, histórico e PCs montados)"}]
        for chave in ORDEM_CATEGORIAS + ORDEM_CATEGORIAS_CASA:
            opcoes.append({"chave": chave, "rotulo": CATEGORIAS[chave]})
        return opcoes

    def exportar_dados(self, chave):
        categoria = None if chave == "__tudo__" else chave
        nome_sugerido = f"zandonadi-radar-{chave if categoria else 'tudo'}.json"
        resultado = self._window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename=nome_sugerido,
            file_types=("Zandonadi Radar (*.json)",),
        )
        if not resultado:
            return {"ok": False, "cancelado": True}
        caminho = resultado[0]
        dados = db.exportar_dados(categoria)
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
        except OSError as e:
            return {"ok": False, "erro": str(e)}

        resumo = f"{len(dados['produtos'])} produto(s) exportado(s)."
        if not categoria and dados["builds"]:
            resumo += f" {len(dados['builds'])} PC(s) montado(s) incluído(s)."
        return {"ok": True, "resumo": resumo, "caminho": caminho}

    def escolher_arquivo_importacao(self):
        resultado = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("Zandonadi Radar (*.json)", "Todos os arquivos (*.*)"),
        )
        if not resultado:
            return {"ok": False, "cancelado": True}
        caminho = resultado[0]
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return {"ok": False, "erro": str(e)}

        if not isinstance(dados, dict) or dados.get("formato") != db.FORMATO_EXPORTACAO:
            return {"ok": False, "erro": "Esse arquivo não parece ser uma exportação do Zandonadi Radar."}

        self._importacao_pendente = dados
        qtd_produtos = len(dados.get("produtos", []))
        qtd_builds = len(dados.get("builds", []))
        resumo = f"{qtd_produtos} produto(s)" + (f" e {qtd_builds} PC(s) montado(s)" if qtd_builds else "")
        return {"ok": True, "resumo": resumo}

    def confirmar_importacao(self, substituir):
        dados = self._importacao_pendente
        if not dados:
            return {"ok": False, "erro": "Nenhum arquivo selecionado."}
        novos_produtos, novos_builds = db.importar_dados(dados, substituir=substituir)
        self._importacao_pendente = None
        return {"ok": True, "novos_produtos": novos_produtos, "novos_builds": novos_builds}
