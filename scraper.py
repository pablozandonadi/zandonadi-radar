# -*- coding: utf-8 -*-
"""
Scraper de preços — busca um termo em várias lojas e devolve uma lista
de resultados: [{"loja": ..., "titulo": ..., "preco": float, "url": ...}, ...]

Como cada loja muda o site de tempos em tempos, se uma parar de bater,
normalmente basta ajustar a função correspondente aqui embaixo.
Dica para depurar: rode `python scraper.py "nome do produto"` no terminal
que ele imprime tudo que encontrou, loja por loja — incluindo avisos de
bloqueio e quantos produtos foram descartados por não serem relevantes.

--------------------------------------------------------------------------
Como o anti-bloqueio funciona (ver _buscar_com_camadas)
--------------------------------------------------------------------------
Para cada loja, tentamos obter o HTML da página de busca em até 3 "camadas",
da mais rápida para a mais lenta, parando assim que uma delas trouxer
resultados de verdade:

  1) curl_cffi  — faz a requisição imitando o "footprint" TLS/HTTP de um
     Chrome de verdade. Isso passa por boa parte dos bloqueios que pegam a
     biblioteca `requests` comum mesmo quando os cabeçalhos parecem certos
     (é uma técnica de detecção mais profunda que várias lojas usam).
  2) requests   — uma sessão "aquecida" (visita a home antes da busca, para
     ganhar cookies) com cabeçalhos completos de navegador.
  3) Selenium   — abre um Chrome headless de verdade. É o mais lento, mas é
     praticamente indistinguível de um usuário real e também resolve o caso
     de lojas (como a KaBuM!) que só montam a lista de produtos via
     JavaScript. Só é usado se USAR_SELENIUM_FALLBACK estiver True (em
     config.py) e o Selenium/Chrome estiverem instalados.

--------------------------------------------------------------------------
Como o filtro de relevância funciona (ver eh_relevante)
--------------------------------------------------------------------------
As lojas costumam devolver, junto com os resultados da busca, produtos de
seções de "relacionados"/"quem viu este também viu"/categoria inteira. Para
não poluir sua lista com coisa que você não pediu, todo produto extraído
passa por um teste: ele só é mantido se o título contiver as mesmas
"palavras-chave" do termo que você buscou (todo número do termo precisa
aparecer no título, e a maior parte das palavras também). Ajuste
LIMIAR_RELEVANCIA em config.py se achar o filtro rígido/frouxo demais.
"""

import json
import random
import re
import time
import traceback
import unicodedata
from urllib.parse import quote, quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from config import HTTP_TIMEOUT, LIMIAR_RELEVANCIA, USAR_SELENIUM_FALLBACK, USER_AGENT
from llm import esta_configurado, extrair_com_llm, filtrar_relevantes_llm

HEADERS_NAVEGADOR = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


# --------------------------------------------------------------------------
# Utilidades de preço
# --------------------------------------------------------------------------

def parse_preco(texto):
    """
    Converte um texto tipo 'R$ 2.099,99' ou 'R$ 1,579.96' em float 2099.99 / 1579.96.
    Retorna None se não conseguir.
    """
    if not texto:
        return None
    t = texto.replace("R$", "").strip()
    t = re.sub(r"[^\d.,]", "", t)
    if not t:
        return None

    if "," in t and "." in t:
        # o último separador encontrado é o decimal
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        # só vírgula: assume decimal se tiver 2 casas depois dela
        partes = t.split(",")
        if len(partes[-1]) == 2:
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    # só ponto (ou nenhum separador) já fica como está

    try:
        valor = float(t)
        if valor <= 0:
            return None
        return valor
    except ValueError:
        return None


PRECO_REGEX = re.compile(r"R\$\s*[\d.,]+")


def extrair_preco_final(texto_bloco):
    """
    Dado o texto de um "card" de produto (pode ter preço "de/por", parcelas
    etc.), tenta achar o preço final (o que vem depois de 'por', que é o
    preço à vista/com desconto). Se não achar 'por', usa o primeiro valor.
    """
    m = re.search(r"por:?\s*(R\$\s*[\d.,]+)", texto_bloco, re.IGNORECASE)
    if m:
        return parse_preco(m.group(1))

    todos = PRECO_REGEX.findall(texto_bloco)
    if not todos:
        return None
    return parse_preco(todos[0])


# --------------------------------------------------------------------------
# Filtro de relevância — evita produtos que não têm nada a ver com a busca
# --------------------------------------------------------------------------

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "com", "para", "sem", "e", "a", "o",
    "the", "novo", "nova", "original", "novo modelo",
}


def _normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    return texto


def _tokens_significativos(texto):
    palavras = _normalizar(texto).split()
    return [p for p in palavras if p not in _STOPWORDS and len(p) > 1]


_TAMANHO_MAX_SUFIXO_OBRIGATORIO = 3

# Sufixos de nome de modelo que quase sempre indicam um produto DIFERENTE
# (quase sempre mais caro) do que a versão "pelada" — ex.: "RTX 5060" e
# "RTX 5060 Ti" são placas diferentes. Diferente de um sufixo qualquer
# (tratado como obrigatório só quando está no termo buscado — ver
# tokens_sufixo abaixo), esta lista também é checada no sentido contrário:
# se o TÍTULO tem um desses sufixos e o termo buscado não pediu ele, o
# título é rejeitado mesmo assim (buscar "rtx 5060" não pode trazer "rtx
# 5060 ti"). Lista pequena de propósito — autodeliberadamente não inclui
# palavras tipo "OC" (overclock de fábrica), que não trocam de produto.
_SUFIXOS_DIFERENCIADORES = {"ti", "super", "xt", "se"}


def eh_relevante(titulo, termo_busca, limiar=None):
    """
    True se `titulo` parece de fato corresponder ao que foi buscado em
    `termo_busca`. Regra: todo "token numérico" do termo (ex.: modelos como
    5700x, 5060, 850w) precisa aparecer no título; toda palavra CURTA (até
    3 letras — ex.: "Ti", "XT", "SE", "GT", "Pro") também precisa aparecer;
    nenhum sufixo de `_SUFIXOS_DIFERENCIADORES` pode aparecer no título sem
    também estar no termo buscado (e vice-versa não se aplica — é só nessa
    direção, pra não trazer um modelo mais caro/diferente que não foi
    pedido); e pelo menos `limiar` (fração de 0 a 1) das palavras restantes
    (mais longas, geralmente só descritivas) também precisam aparecer.
    """
    if limiar is None:
        limiar = LIMIAR_RELEVANCIA
    if not titulo:
        return False

    tokens_termo = _tokens_significativos(termo_busca)
    if not tokens_termo:
        return True

    tokens_titulo = set(_tokens_significativos(titulo))

    tokens_numericos = [t for t in tokens_termo if any(ch.isdigit() for ch in t)]
    tokens_sufixo = [
        t for t in tokens_termo
        if t not in tokens_numericos and len(t) <= _TAMANHO_MAX_SUFIXO_OBRIGATORIO
    ]
    for t in tokens_numericos + tokens_sufixo:
        if t not in tokens_titulo:
            return False

    # O título tem um sufixo "de outro modelo" (ex.: "Ti") que o termo
    # buscado não pediu? Então não é o mesmo produto, mesmo que todo o
    # resto bata.
    sufixos_nao_pedidos = _SUFIXOS_DIFERENCIADORES - set(tokens_termo)
    if sufixos_nao_pedidos & tokens_titulo:
        return False

    tokens_alfa = [t for t in tokens_termo if t not in tokens_numericos and t not in tokens_sufixo]
    if tokens_alfa:
        encontrados = sum(1 for t in tokens_alfa if t in tokens_titulo)
        if (encontrados / len(tokens_alfa)) < limiar:
            return False

    return True


def _eh_link_ignorado(url_produto, dominio, caminhos_ignorar):
    caminho = url_produto.split(dominio, 1)[-1]
    return any(caminho.startswith(c) or caminho == c.rstrip("/") for c in caminhos_ignorar)


def _href_bate_algum(href, criterios):
    """
    `criterios` pode misturar trechos simples (checados com `in`, como
    sempre) e padrões regex já compilados (checados com `.search()`) — útil
    quando o link do produto não tem um trecho fixo em comum, só um formato
    (ex.: termina em "_123456" ou em "/p").
    """
    for c in criterios:
        if hasattr(c, "search"):
            if c.search(href):
                return True
        elif c in href:
            return True
    return False


# --------------------------------------------------------------------------
# Extração genérica de "cards" de produto a partir do HTML
# --------------------------------------------------------------------------

def _extrair_produtos_generico(html, base_url, contem_no_href, min_price=1, max_resultados=15):
    """
    Estratégia genérica: procura links <a> cujo href contenha algum dos
    trechos em `contem_no_href` (ex: '/produto/'), sobe até achar um bloco
    de texto com preço, e usa isso como card do produto.
    """
    soup = BeautifulSoup(html, "html.parser")
    resultados = []
    vistos = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _href_bate_algum(href, contem_no_href):
            continue

        url_completa = urljoin(base_url, href)
        if url_completa in vistos:
            continue

        # sobe alguns níveis até achar um bloco com "R$"
        bloco = a
        texto = ""
        for _ in range(5):
            if bloco is None:
                break
            texto = bloco.get_text(" ", strip=True)
            if "R$" in texto:
                break
            bloco = bloco.parent

        if "R$" not in texto:
            continue

        preco = extrair_preco_final(texto)
        if preco is None or preco < min_price:
            continue

        titulo = a.get_text(strip=True)
        titulo_suspeito = (not titulo) or ("R$" in titulo) or (len(titulo) < 12)
        if titulo_suspeito:
            # Em alguns sites o <a> do card envolve a imagem, o título E o
            # preço juntos (ou só um selinho tipo "Bivolt") — get_text()
            # viraria uma mistura de tudo isso ou pegaria só o selinho. O alt
            # da imagem (pensado pra acessibilidade) quase sempre traz só o
            # nome do produto, então é uma fonte melhor quando existir.
            img = a.find("img")
            if img is not None:
                alt_titulo = (img.get("alt") or img.get("title") or "").strip()
                if len(alt_titulo) >= 12:
                    titulo = alt_titulo
        if not titulo or "R$" in titulo:
            titulo = texto[:80]

        vistos.add(url_completa)
        resultados.append({"titulo": titulo.strip(), "preco": preco, "url": url_completa})

        if len(resultados) >= max_resultados:
            break

    return resultados


# --------------------------------------------------------------------------
# Camadas de obtenção de HTML (anti-bloqueio)
# --------------------------------------------------------------------------

def _obter_html_curl_cffi(url, referer=None):
    """Camada 1: imita o footprint TLS/HTTP do Chrome. Rápido, sem navegador."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None
    try:
        sessao = cffi_requests.Session(impersonate="chrome")
        sessao.headers.update(HEADERS_NAVEGADOR)
        if referer:
            try:
                sessao.get(referer, timeout=HTTP_TIMEOUT)
            except Exception:
                pass
            sessao.headers["Referer"] = referer
        resp = sessao.get(url, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            print(f"[curl_cffi] {url} respondeu {resp.status_code}")
            return None
        return resp.text
    except Exception as e:
        print(f"[curl_cffi] erro em {url}: {e}")
        return None


def _obter_html_requests(url, referer=None):
    """Camada 2: requests comum, com sessão 'aquecida' visitando a home antes."""
    try:
        sessao = requests.Session()
        sessao.headers.update(HEADERS_NAVEGADOR)
        if referer:
            try:
                sessao.get(referer, timeout=HTTP_TIMEOUT)
            except requests.RequestException:
                pass
            sessao.headers["Referer"] = referer
        resp = sessao.get(url, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            print(f"[requests] {url} respondeu {resp.status_code}")
            return None
        return resp.text
    except requests.RequestException as e:
        print(f"[requests] erro de conexão em {url}: {e}")
        return None


def _obter_html_selenium(url, driver, espera_extra=0):
    """Camada 3: Chrome headless de verdade via Selenium.

    `espera_extra` (segundos) dá mais tempo antes de ler a página — algumas
    lojas (KaBuM!) montam a listagem via JavaScript e podem não ter
    terminado de renderizar no tempo padrão.
    """
    if driver is None:
        return None
    try:
        driver.get(url)
        time.sleep(2.5 + espera_extra)
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 900);")
            time.sleep(0.4)
        return driver.page_source
    except Exception as e:
        print(f"[Selenium] erro ao carregar {url}: {e}")
        return None


def _iniciar_driver_selenium():
    if not USAR_SELENIUM_FALLBACK:
        return None
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        print(
            "[Selenium] não instalado — algumas lojas podem retornar menos "
            "resultados. Rode: pip install selenium (e tenha o Google Chrome instalado)."
        )
        return None

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1366,900")
    options.add_argument(f"user-agent={USER_AGENT}")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    try:
        return webdriver.Chrome(options=options)
    except Exception as e:
        print(f"[Selenium] não foi possível abrir o Chrome headless: {e}")
        return None


def _buscar_com_camadas(url, parse_fn, referer=None, driver_selenium=None, espera_selenium_extra=0):
    """
    Tenta obter e interpretar a página em camadas (da mais rápida para a
    mais robusta), parando assim que uma camada trouxer resultados.
    """
    obtentores = [
        lambda: _obter_html_curl_cffi(url, referer),
        lambda: _obter_html_requests(url, referer),
    ]
    if driver_selenium is not None:
        obtentores.append(lambda: _obter_html_selenium(url, driver_selenium, espera_extra=espera_selenium_extra))

    for obter_html in obtentores:
        html = obter_html()
        if not html:
            continue
        resultados = parse_fn(html)
        if resultados:
            return resultados
    return []


# --------------------------------------------------------------------------
# Pichau
# --------------------------------------------------------------------------

_CAMINHOS_IGNORAR_PICHAU = (
    "/search", "/marca/", "/computadores", "/hardware", "/perifericos",
    "/monitores", "/cadeiras", "/eletronicos", "/notebooks", "/mochilas",
    "/vestuario", "/video-games", "/redes-wireless", "/casa-inteligente",
    "/casa-e-lazer", "/energetico", "/realidadevirtual", "/openbox",
    "/pets", "/account", "/cart", "/quem-somos", "/termos-de-aceite",
    "/politica-de-privacidade", "/atendimento", "/monte-seu-pc",
    "/kit-upgrade", "/promocao",
)


def buscar_pichau(termo, max_resultados=10, driver_selenium=None):
    url = f"https://www.pichau.com.br/search?q={quote(termo)}"

    def parse(html):
        produtos = _extrair_produtos_generico(
            html, url, contem_no_href=["pichau.com.br/"], max_resultados=max_resultados * 4,
        )
        produtos = [
            p for p in produtos
            if not _eh_link_ignorado(p["url"], "pichau.com.br", _CAMINHOS_IGNORAR_PICHAU)
        ]
        # Filtro de relevância (heurística ou LLM) é aplicado de forma
        # centralizada em buscar_em_todas_as_lojas — aqui só limpamos links
        # que claramente não são produto (categorias, carrinho etc.).
        return produtos

    resultados = _buscar_com_camadas(
        url, parse, referer="https://www.pichau.com.br/", driver_selenium=driver_selenium
    )
    for p in resultados:
        p["loja"] = "Pichau"
    return resultados


# --------------------------------------------------------------------------
# Terabyte Shop
# --------------------------------------------------------------------------

def buscar_terabyte(termo, max_resultados=10, driver_selenium=None):
    url = f"https://www.terabyteshop.com.br/busca?str={quote(termo)}"

    def parse(html):
        return _extrair_produtos_generico(
            html, url, contem_no_href=["/produto/"], max_resultados=max_resultados * 3,
        )

    resultados = _buscar_com_camadas(
        url, parse, referer="https://www.terabyteshop.com.br/", driver_selenium=driver_selenium
    )
    for p in resultados:
        p["loja"] = "Terabyte Shop"
    return resultados


# --------------------------------------------------------------------------
# KaBuM!  (a listagem de produtos é montada via JavaScript -> quase sempre
# precisa da camada Selenium; as camadas rápidas são tentadas mesmo assim
# porque volta e meia funcionam também.)
# --------------------------------------------------------------------------

def buscar_kabum(termo, max_resultados=10, driver_selenium=None):
    url = f"https://www.kabum.com.br/busca/{quote(termo)}"

    def parse(html):
        return _extrair_produtos_generico(
            html, url, contem_no_href=["/produto/"], max_resultados=max_resultados * 3,
        )

    resultados = _buscar_com_camadas(
        url, parse, referer="https://www.kabum.com.br/", driver_selenium=driver_selenium,
        espera_selenium_extra=2.5,
    )
    for p in resultados:
        p["loja"] = "KaBuM!"
    return resultados


# --------------------------------------------------------------------------
# Amazon.com.br
# --------------------------------------------------------------------------

def buscar_amazon(termo, max_resultados=10, driver_selenium=None):
    url = f"https://www.amazon.com.br/s?k={quote_plus(termo)}"

    def parse(html):
        soup = BeautifulSoup(html, "html.parser")
        resultados = []
        limite_bruto = max_resultados * 3

        cards = soup.select('div[data-component-type="s-search-result"]')
        for card in cards:
            link_el = card.select_one('a.a-link-normal[href*="/dp/"]') or card.select_one("h2 a")
            if link_el is None or not link_el.get("href"):
                continue
            url_completa = urljoin(url, link_el["href"])

            titulo_el = card.select_one("h2 span") or link_el
            titulo = titulo_el.get_text(strip=True)

            preco_el = card.select_one("span.a-price > span.a-offscreen")
            preco = parse_preco(preco_el.get_text(strip=True)) if preco_el else None
            if preco is None:
                continue

            # Filtro de relevância (heurística ou LLM) é aplicado depois, de
            # forma centralizada, em buscar_em_todas_as_lojas.
            resultados.append({"titulo": titulo, "preco": preco, "url": url_completa})
            if len(resultados) >= limite_bruto:
                break

        if not resultados:
            # a Amazon muda o layout com frequência: se os seletores acima
            # não acharam nada, cai para a extração genérica por padrão de link
            resultados = _extrair_produtos_generico(
                html, url, contem_no_href=["/dp/"], max_resultados=limite_bruto,
            )

        return resultados

    resultados = _buscar_com_camadas(
        url, parse, referer="https://www.amazon.com.br/", driver_selenium=driver_selenium
    )
    for p in resultados:
        p["loja"] = "Amazon.com.br"
    return resultados


# --------------------------------------------------------------------------
# Mercado Livre
# --------------------------------------------------------------------------

def buscar_mercadolivre(termo, max_resultados=10, driver_selenium=None):
    slug = quote(termo.strip().replace(" ", "-"))
    url = f"https://lista.mercadolivre.com.br/{slug}"

    def parse(html):
        soup = BeautifulSoup(html, "html.parser")
        resultados = []
        limite_bruto = max_resultados * 3

        cards = (
            soup.select("li.ui-search-layout__item")
            or soup.select("div.poly-card")
            or soup.select("div.ui-search-result__wrapper")
        )
        for card in cards:
            link_el = (
                card.select_one("a.ui-search-link")
                or card.select_one("a.poly-component__title")
                or card.find("a", href=True)
            )
            if link_el is None or not link_el.get("href"):
                continue
            url_produto = link_el["href"]

            titulo_el = (
                card.select_one("h2.ui-search-item__title")
                or card.select_one(".poly-component__title")
                or link_el
            )
            titulo = titulo_el.get_text(strip=True)

            preco_el = card.select_one("span.andes-money-amount__fraction")
            if preco_el is not None:
                preco = parse_preco(preco_el.get_text(strip=True))
            else:
                preco = extrair_preco_final(card.get_text(" ", strip=True))
            if preco is None:
                continue

            # Filtro de relevância (heurística ou LLM) é aplicado depois, de
            # forma centralizada, em buscar_em_todas_as_lojas.
            resultados.append({"titulo": titulo, "preco": preco, "url": url_produto})
            if len(resultados) >= limite_bruto:
                break

        if not resultados:
            resultados = _extrair_produtos_generico(
                html, url, contem_no_href=["MLB-", "/p/", ".html"], max_resultados=limite_bruto,
            )

        return resultados

    resultados = _buscar_com_camadas(
        url, parse, referer="https://www.mercadolivre.com.br/", driver_selenium=driver_selenium
    )
    for p in resultados:
        p["loja"] = "Mercado Livre"
    return resultados


# --------------------------------------------------------------------------
# Lojas de eletrodomésticos e móveis (usadas só na categoria "Eletrodomésticos
# e Móveis" — ver LOJAS_ELETRO_MOVEIS em config.py). Da lista original de 10
# lojas, 4 ficaram de fora por terem proteção anti-robô forte demais pra
# valer a pena tentar contornar (o que também não é algo que devemos fazer):
#   - Magazine Luiza, Ponto Frio e Casas Bahia bloqueiam com erro 403 da
#     Akamai até o Chrome automatizado de verdade (Selenium), não só
#     requisições simples — a mesma proteção nas 3, provavelmente por serem
#     do mesmo grupo/infra.
#   - Leroy Merlin chega a servir um CAPTCHA de verdade (DataDome) pro
#     Chrome automatizado.
#   - Etna simplesmente fechou (o domínio hoje redireciona pra "Openbox2").
# --------------------------------------------------------------------------

def buscar_fastshop(termo, max_resultados=10, driver_selenium=None):
    # O domínio de verdade da loja (a busca funciona por trás de
    # www.fastshop.com.br, mas o site inteiro roda em site.fastshop.com.br).
    url = f"https://site.fastshop.com.br/s?q={quote_plus(termo)}"

    def parse(html):
        return _extrair_produtos_generico(
            html, url, contem_no_href=["_prd"], max_resultados=max_resultados * 3,
        )

    resultados = _buscar_com_camadas(
        url, parse, referer="https://site.fastshop.com.br/", driver_selenium=driver_selenium
    )
    for p in resultados:
        p["loja"] = "Fast Shop"
    return resultados


def buscar_madeiramadeira(termo, max_resultados=10, driver_selenium=None):
    url = f"https://www.madeiramadeira.com.br/busca?q={quote_plus(termo)}"

    def parse(html):
        return _extrair_produtos_generico(
            html, url, contem_no_href=[".html"], max_resultados=max_resultados * 3,
        )

    resultados = _buscar_com_camadas(
        url, parse, referer="https://www.madeiramadeira.com.br/", driver_selenium=driver_selenium
    )
    for p in resultados:
        p["loja"] = "Madeira Madeira"
    return resultados


_REGEX_LINK_PRODUTO_COM_P = re.compile(r"/p(?:$|[?#])")


def buscar_tokstok(termo, max_resultados=10, driver_selenium=None):
    url = f"https://www.tokstok.com.br/resultado-busca/{quote(termo)}?q={quote_plus(termo)}"

    def parse(html):
        return _extrair_produtos_generico(
            html, url, contem_no_href=[_REGEX_LINK_PRODUTO_COM_P], max_resultados=max_resultados * 3,
        )

    resultados = _buscar_com_camadas(
        url, parse, referer="https://www.tokstok.com.br/", driver_selenium=driver_selenium
    )
    for p in resultados:
        p["loja"] = "Tok&Stok"
    return resultados


def buscar_americanas(termo, max_resultados=10, driver_selenium=None):
    url = f"https://www.americanas.com.br/s?q={quote_plus(termo)}"

    def parse(html):
        return _extrair_produtos_generico(
            html, url, contem_no_href=[_REGEX_LINK_PRODUTO_COM_P], max_resultados=max_resultados * 3,
        )

    resultados = _buscar_com_camadas(
        url, parse, referer="https://www.americanas.com.br/", driver_selenium=driver_selenium
    )
    for p in resultados:
        p["loja"] = "Americanas"
    return resultados


_SCRIPT_COLETA_SHADOW_DOM = """
function coletar(root, out) {
    root.querySelectorAll('a[href]').forEach(function(a) {
        var href = a.getAttribute('href');
        if (href && href.indexOf('.html') !== -1) {
            var texto = a.textContent || '';
            if (texto.indexOf('R$') !== -1) {
                out.push([href, texto]);
            }
        }
    });
    root.querySelectorAll('*').forEach(function(el) {
        if (el.shadowRoot) coletar(el.shadowRoot, out);
    });
}
var out = [];
coletar(document, out);
return out;
"""


def buscar_mobly(termo, max_resultados=10, driver_selenium=None):
    """
    A Mobly monta a listagem inteira dentro de Shadow DOM (componentes web
    "fechados" por trás de um `<a>` só) — o HTML que qualquer requisição
    "crua" recebe (curl_cffi, requests, e até o `page_source` do Selenium)
    não contém esses cards, só o esqueleto da página. Por isso essa loja não
    usa `_extrair_produtos_generico`/`_buscar_com_camadas` como as outras:
    só funciona mesmo com o Chrome do Selenium de verdade, lendo os links
    "por dentro" via JavaScript, e não tem uma "camada rápida" possível.
    """
    if driver_selenium is None:
        return []

    url = f"https://www.mobly.com.br/catalog?terms={quote_plus(termo)}"
    try:
        driver_selenium.get(url)
        time.sleep(5)
        for _ in range(2):
            driver_selenium.execute_script("window.scrollBy(0, 900);")
            time.sleep(0.6)
        pares = driver_selenium.execute_script(_SCRIPT_COLETA_SHADOW_DOM) or []
    except Exception as e:
        print(f"[Mobly/Selenium] erro ao carregar {url}: {e}")
        return []

    resultados = []
    vistos = set()
    limite_bruto = max_resultados * 3
    for href, texto in pares:
        url_completa = urljoin(url, href)
        if url_completa in vistos:
            continue
        preco = extrair_preco_final(texto)
        if preco is None:
            continue

        slug = href.rsplit("/", 1)[-1]
        slug = re.sub(r"-\d+\.html.*$", "", slug)
        titulo = slug.replace("-", " ").strip().capitalize() or texto[:80]

        vistos.add(url_completa)
        resultados.append({"titulo": titulo, "preco": preco, "url": url_completa})
        if len(resultados) >= limite_bruto:
            break

    for p in resultados:
        p["loja"] = "Mobly"
    return resultados


# --------------------------------------------------------------------------
# Adicionar produto por link direto (em vez de buscar por termo)
# --------------------------------------------------------------------------

_DOMINIO_PARA_LOJA = {
    "kabum.com.br": "KaBuM!",
    "pichau.com.br": "Pichau",
    "terabyteshop.com.br": "Terabyte Shop",
    "amazon.com.br": "Amazon.com.br",
    "mercadolivre.com.br": "Mercado Livre",
    "mercadolibre.com": "Mercado Livre",
    "fastshop.com.br": "Fast Shop",
    "madeiramadeira.com.br": "Madeira Madeira",
    "mobly.com.br": "Mobly",
    "tokstok.com.br": "Tok&Stok",
    "americanas.com.br": "Americanas",
    # Domínios só pra rotular certo caso o usuário cole um link direto dessas
    # lojas em "Adicionar por link" — elas NÃO entram na busca automática
    # (ver o comentário grande acima de buscar_fastshop) por terem proteção
    # anti-robô forte demais pra tentar contornar.
    "magazineluiza.com.br": "Magazine Luiza",
    "pontofrio.com.br": "Ponto Frio",
    "casasbahia.com.br": "Casas Bahia",
    "leroymerlin.com.br": "Leroy Merlin",
}


def _loja_pelo_dominio(url):
    for dominio, loja in _DOMINIO_PARA_LOJA.items():
        if dominio in url:
            return loja
    return "Loja"


def _extrair_preco_titulo_pagina(html):
    """
    Extrai título + preço de uma página de PRODUTO único (não uma listagem
    de busca). Tenta, em ordem: dados estruturados JSON-LD (schema.org
    Product/Offer, o jeito mais confiável quando a loja publica), meta tags
    og:title/product:price:amount, e por fim um fallback genérico (<title>
    da página + primeiro "R$" relevante no texto).
    """
    soup = BeautifulSoup(html, "html.parser")
    titulo = None
    preco = None

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        blocos = dados if isinstance(dados, list) else [dados]
        for bloco in blocos:
            if not isinstance(bloco, dict):
                continue
            if bloco.get("@type") != "Product":
                grafo = bloco.get("@graph")
                if isinstance(grafo, list):
                    bloco = next(
                        (item for item in grafo if isinstance(item, dict) and item.get("@type") == "Product"),
                        {},
                    )
            if bloco.get("@type") == "Product":
                titulo = titulo or bloco.get("name")
                oferta = bloco.get("offers")
                if isinstance(oferta, list):
                    oferta = oferta[0] if oferta else {}
                if isinstance(oferta, dict):
                    preco_bruto = oferta.get("price") or oferta.get("lowPrice")
                    if preco_bruto is not None:
                        try:
                            preco = float(preco_bruto)
                        except (TypeError, ValueError):
                            preco = parse_preco(str(preco_bruto))
        if titulo and preco is not None:
            break

    if not titulo:
        meta_titulo = soup.find("meta", property="og:title")
        if meta_titulo and meta_titulo.get("content"):
            titulo = meta_titulo["content"]
    if preco is None:
        meta_preco = soup.find("meta", property="product:price:amount")
        if meta_preco and meta_preco.get("content"):
            preco = parse_preco(meta_preco["content"])

    texto_visivel = soup.get_text(" ", strip=True)
    if not titulo and soup.title:
        titulo = soup.title.get_text(strip=True)
    if preco is None:
        preco = extrair_preco_final(texto_visivel)

    if preco is None:
        # Último recurso, só se o LLM estiver ativado (llm_config.py) — a
        # loja pode ter mudado o layout a ponto do HTML/regex não acharem
        # nada; o LLM lê o texto visível e tenta achar o preço mesmo assim.
        titulo_llm, preco_llm = extrair_com_llm(texto_visivel)
        if preco_llm is not None:
            preco = preco_llm
            titulo = titulo or titulo_llm

    return titulo, preco


def buscar_produto_por_url(url, callback_progresso=None):
    """
    Em vez de pesquisar um termo, lê diretamente a página de um produto
    (link colado pelo usuário) e extrai título + preço. Usado tanto para
    cadastrar um item por link quanto para "atualizar preços" de itens
    cadastrados assim. Retorna [{"loja", "titulo", "preco", "url"}] ou []
    se não conseguir ler um preço.
    """
    loja = _loja_pelo_dominio(url)
    partes = url.split("/")
    referer = f"{partes[0]}//{partes[2]}/" if len(partes) > 2 else None

    if callback_progresso:
        callback_progresso(loja, "lendo a página do produto")

    def parse(html):
        titulo, preco = _extrair_preco_titulo_pagina(html)
        if preco is None:
            return []
        return [{"titulo": (titulo or url).strip(), "preco": preco, "url": url}]

    driver_selenium = _iniciar_driver_selenium()
    try:
        resultados = _buscar_com_camadas(
            url, parse, referer=referer, driver_selenium=driver_selenium, espera_selenium_extra=1.5
        )
    finally:
        if driver_selenium is not None:
            try:
                driver_selenium.quit()
            except Exception:
                pass

    for p in resultados:
        p["loja"] = loja

    if callback_progresso:
        callback_progresso(loja, f"{len(resultados)} encontrado(s)" if resultados else "não foi possível ler o preço")

    return resultados


# --------------------------------------------------------------------------
# Função principal: busca em todas as lojas
# --------------------------------------------------------------------------

BUSCADORES = {
    "KaBuM!": buscar_kabum,
    "Pichau": buscar_pichau,
    "Terabyte Shop": buscar_terabyte,
    "Amazon.com.br": buscar_amazon,
    "Mercado Livre": buscar_mercadolivre,
    "Fast Shop": buscar_fastshop,
    "Madeira Madeira": buscar_madeiramadeira,
    "Mobly": buscar_mobly,
    "Tok&Stok": buscar_tokstok,
    "Americanas": buscar_americanas,
}


def buscar_em_todas_as_lojas(termo, lojas=None, callback_progresso=None, max_por_loja=8, cancelar_evento=None):
    """
    Busca `termo` em todas as lojas (ou só nas listadas em `lojas`).
    callback_progresso(nome_loja, status) é chamado antes/depois de cada loja
    (útil para atualizar a interface). Retorna lista única com todos os resultados.

    `cancelar_evento`, se passado (um threading.Event), é checado entre uma
    loja e outra — se estiver "setado", a busca para imediatamente e devolve
    só o que já tinha sido encontrado até então.
    """
    lojas = lojas or list(BUSCADORES.keys())
    todos_resultados = []

    def cancelada():
        return cancelar_evento is not None and cancelar_evento.is_set()

    # Um único Chrome headless é reaproveitado para todas as lojas da busca
    # (em vez de abrir um novo por loja) — bem mais rápido.
    driver_selenium = _iniciar_driver_selenium()

    try:
        for nome_loja in lojas:
            if cancelada():
                break
            funcao = BUSCADORES.get(nome_loja)
            if not funcao:
                continue
            if callback_progresso:
                callback_progresso(nome_loja, "buscando")
            try:
                resultados = funcao(termo, max_resultados=max_por_loja, driver_selenium=driver_selenium)
                # Relevância: com o LLM ativado (llm_config.py) ele julga
                # sozinho — entende sinônimos/abreviações que a regra simples
                # não pega (ex.: "QHD" == "QuadHD"). Sem LLM, usa o filtro por
                # palavras/números de sempre.
                resultados_llm = filtrar_relevantes_llm(termo, resultados) if esta_configurado() else None
                if resultados_llm is not None:
                    resultados = resultados_llm
                else:
                    # LLM desligado, ou a chamada falhou (rede, cota etc.) —
                    # cai pro filtro por palavras/números de sempre.
                    resultados = [p for p in resultados if eh_relevante(p["titulo"], termo)]
                resultados = resultados[:max_por_loja]
            except Exception:
                traceback.print_exc()
                resultados = []
            todos_resultados.extend(resultados)
            if callback_progresso:
                if resultados:
                    callback_progresso(nome_loja, f"{len(resultados)} encontrados")
                else:
                    callback_progresso(
                        nome_loja, "0 resultados relevantes (loja pode estar bloqueando ou fora do ar)"
                    )
            if cancelada():
                break
            # pequena pausa entre lojas — reduz a chance de sinalizar como robô
            time.sleep(random.uniform(0.4, 1.1))
    finally:
        if driver_selenium is not None:
            try:
                driver_selenium.quit()
            except Exception:
                pass

    todos_resultados.sort(key=lambda r: r["preco"])
    return todos_resultados


if __name__ == "__main__":
    import sys
    termo_teste = " ".join(sys.argv[1:]) or "Ryzen 7 5700X"
    print(f"Buscando: {termo_teste}\n")

    def progresso(loja, status):
        print(f"  [{loja}] {status}")

    resultados = buscar_em_todas_as_lojas(termo_teste, callback_progresso=progresso)
    print(f"\nTotal: {len(resultados)} resultados\n")
    for r in resultados:
        print(f"R$ {r['preco']:.2f}  |  {r['loja']:<14}  |  {r['titulo'][:70]}")
        print(f"    {r['url']}")
