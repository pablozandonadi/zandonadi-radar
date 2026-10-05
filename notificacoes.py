# -*- coding: utf-8 -*-
"""
Envio de alertas por e-mail (Rotinas). Usa smtplib puro — sem serviço
terceiro, sem custo. As credenciais do remetente ficam em email_config.py,
que você preenche localmente (veja as instruções lá).
"""

import smtplib
from email.mime.text import MIMEText
from datetime import datetime

import database as db

try:
    import email_config as cfg
except ImportError:
    # Instalação nova (ex.: via o instalador) sem email_config.py ainda —
    # fica como "remetente não configurado" até o usuário criar o arquivo,
    # em vez de o app inteiro travar na abertura.
    class cfg:
        SMTP_HOST = "smtp.gmail.com"
        SMTP_PORT = 587
        SMTP_EMAIL = None
        SMTP_SENHA_APP = None


def remetente_configurado():
    return bool(cfg.SMTP_EMAIL and cfg.SMTP_SENHA_APP)


def enviar_alerta_email(destino, assunto, corpo):
    """Retorna (True, None) se enviou, ou (False, motivo) se não conseguiu."""
    if not cfg.SMTP_EMAIL or not cfg.SMTP_SENHA_APP:
        return False, "e-mail remetente não configurado (preencha email_config.py)"

    msg = MIMEText(corpo, "plain", "utf-8")
    msg["Subject"] = assunto
    msg["From"] = cfg.SMTP_EMAIL
    msg["To"] = destino

    try:
        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=20) as servidor:
            servidor.starttls()
            servidor.login(cfg.SMTP_EMAIL, cfg.SMTP_SENHA_APP)
            servidor.sendmail(cfg.SMTP_EMAIL, [destino], msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)


def verificar_e_alertar_queda_produto(produto_id):
    """
    Chame isso depois de registrar um preço novo (db.registrar_precos) pra
    um produto — se esse produto tem um alerta de % configurado (ver tela
    de Configurações / botão 🔔 na lista) e a queda bateu ou passou do
    percentual, manda um e-mail pro endereço padrão configurado. Fail-open:
    sem alerta configurado, sem e-mail padrão definido, ou sem remetente
    configurado, só não faz nada — nunca quebra a busca por causa disso.
    """
    produto = db.obter_produto(produto_id)
    if not produto or not produto.get("alerta_queda_percentual"):
        return

    destino = db.obter_configuracao("email_alerta_padrao")
    if not destino:
        return

    variacao = db.variacao_preco(produto_id)
    if not variacao or variacao["status"] != "verde" or not variacao.get("anterior_min"):
        return

    queda_percentual = abs(variacao["diferenca"]) / variacao["anterior_min"] * 100
    if queda_percentual < produto["alerta_queda_percentual"]:
        return

    assunto = f"💰 {produto['nome']} caiu {queda_percentual:.0f}%"
    corpo = (
        f"“{produto['nome']}” caiu de R$ {variacao['anterior_min']:.2f} para R$ {variacao['atual']:.2f} "
        f"({queda_percentual:.0f}% de queda — seu alerta era a partir de {produto['alerta_queda_percentual']:.0f}%).\n\n"
        f"Checado em {datetime.now().strftime('%d/%m/%Y %H:%M')} pelo Zandonadi Radar."
    )
    enviar_alerta_email(destino, assunto, corpo)
