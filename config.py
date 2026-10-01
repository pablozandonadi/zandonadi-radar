# -*- coding: utf-8 -*-
"""
Configurações centrais do Rastreador de Preços.

Se uma loja parar de funcionar (o site mudou o layout ou passou a
bloquear as buscas), ajuste apenas as constantes/seletores deste
arquivo e de scraper.py — o resto do programa não precisa mudar.
"""

import os
import sys

# Pasta onde fica o banco de dados SQLite (fica ao lado do programa). Quando
# o app está "congelado" pelo PyInstaller (instalado via o instalador, sem
# Python separado), __file__ aponta pra dentro do pacote interno do
# executável — o jeito certo de achar a pasta de instalação de verdade
# nesse caso é a partir de sys.executable (recomendação oficial do
# PyInstaller), senão o banco "sumiria" a cada reinício.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "precos.db")

# --------------------------------------------------------------------------
# Categorias de produtos que o app organiza
# chave interna -> rótulo mostrado na tela
# --------------------------------------------------------------------------
CATEGORIAS = {
    "processador": "Processador",
    "memoria_ram": "Memória RAM",
    "gabinete": "Gabinete",
    "ssd": "SSD",
    "fonte": "Fonte",
    "monitor": "Monitor",
    "placa_video": "Placa de Vídeo",
    "placa_mae": "Placa Mãe",
    "water_cooler": "Water Cooler",

    # Eletrodomésticos e móveis — área separada de "Montar PC" (ver
    # ORDEM_CATEGORIAS_CASA logo abaixo). Fica no mesmo dicionário porque a
    # tela "Buscar produto" precisa listar TODAS as categorias no combobox.
    "eletrodomesticos_moveis": "Eletrodomésticos e Móveis",
}

# Ordem em que as categorias de PC aparecem no menu e no esqueleto de
# "Montar PC" — só peças de computador entram aqui.
ORDEM_CATEGORIAS = [
    "processador",
    "placa_mae",
    "memoria_ram",
    "placa_video",
    "ssd",
    "fonte",
    "gabinete",
    "water_cooler",
    "monitor",
]

# Eletrodomésticos e móveis — seção própria na barra lateral, sem relação
# com "Montar PC" (cada item aqui é rastreado sozinho, como as peças de PC).
ORDEM_CATEGORIAS_CASA = [
    "eletrodomesticos_moveis",
]

# --------------------------------------------------------------------------
# Lojas suportadas pelo scraper (ver scraper.py)
# --------------------------------------------------------------------------
LOJAS_DISPONIVEIS = ["KaBuM!", "Pichau", "Terabyte Shop", "Amazon.com.br", "Mercado Livre"]

# Lojas extras, usadas só quando a categoria buscada é "Eletrodomésticos e
# Móveis" (ver ORDEM_CATEGORIAS_CASA acima). Da lista original de 10 lojas,
# 4 ficaram de fora por terem proteção anti-robô forte demais pra valer a
# pena tentar contornar — ver o comentário em scraper.py acima de
# buscar_fastshop: Magazine Luiza, Ponto Frio e Casas Bahia bloqueiam com
# erro 403 da Akamai até o Chrome automatizado de verdade, Leroy Merlin
# chega a servir CAPTCHA (DataDome), e a Etna simplesmente fechou.
LOJAS_ELETRO_MOVEIS = [
    "Fast Shop",
    "Madeira Madeira",
    "Mobly",
    "Tok&Stok",
    "Americanas",
]

# --------------------------------------------------------------------------
# Anti-bloqueio
# --------------------------------------------------------------------------
# Várias lojas (principalmente KaBuM!, Amazon e Mercado Livre) usam proteção
# anti-robô que bloqueia requisições "cruas" (biblioteca requests comum),
# mesmo com cabeçalhos de navegador. O scraper tenta, em ordem: 1) uma
# requisição rápida imitando o "footprint" do Chrome (curl_cffi), 2) uma
# requisição comum com sessão/cookies aquecidos e, só se as duas falharem,
# 3) abre um Chrome headless de verdade via Selenium.
#
# Deixe True para ter a maior taxa de sucesso possível (recomendado).
# Se você não quiser instalar o Google Chrome/Selenium, pode deixar False
# — o app continua funcionando, só que algumas lojas podem retornar 0
# resultados quando bloquearem as camadas mais rápidas.
USAR_SELENIUM_FALLBACK = True

# Timeout (segundos) para cada requisição HTTP
HTTP_TIMEOUT = 15

# User-Agent "de navegador" para reduzir bloqueios básicos
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# --------------------------------------------------------------------------
# Filtro de relevância
# --------------------------------------------------------------------------
# Fração mínima (0 a 1) das palavras do termo buscado que precisam aparecer
# no título de um produto para ele ser considerado relevante. Números do
# termo (ex.: "5700x", "5060") sempre precisam aparecer no título, não
# importa esse limiar. Se estiver recebendo produtos "parecidos, mas
# errados", aumente esse valor (ex.: 0.8). Se estiver recebendo poucos
# resultados de lojas que escrevem o nome de um jeito diferente, diminua.
LIMIAR_RELEVANCIA = 0.5
