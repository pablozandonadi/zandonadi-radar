# -*- coding: utf-8 -*-
"""
Envio de alertas por e-mail (Rotinas). Usa smtplib puro — sem serviço
terceiro, sem custo. As credenciais do remetente ficam em email_config.py,
que você preenche localmente (veja as instruções lá).
"""

import smtplib
from email.mime.text import MIMEText

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
