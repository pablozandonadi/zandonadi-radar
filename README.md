# Zandonadi Radar

App de desktop (Windows) para acompanhar preços de peças de PC e
eletrônicos em várias lojas, guardar histórico, mostrar se um preço já foi
mais barato/mais caro, e montar um "PC" somando peças de categorias
diferentes.

## ⬇️ Baixar e instalar (pra quem só quer usar o programa)

**[📥 Baixar o instalador (ZandonadiRadarSetup.exe)](https://github.com/pablozandonadi/zandonadi-radar/releases/latest/download/ZandonadiRadarSetup.exe)**

Esse link já baixa o instalador direto, sempre da versão mais recente —
**não precisa instalar Python, nem abrir terminal, nem mexer em código**.
Só executar o `.exe` baixado e seguir a tela de instalação (ela já pergunta
se você quer configurar a chave da OpenAI e o e-mail de alertas na hora,
com um guia em PDF explicando como conseguir os dois).

> ⚠️ Não use o botão verde **"Code" → "Download ZIP"** desta página — isso
> baixa só o código-fonte (pra quem quer programar/alterar o app), não o
> instalador. O link acima, ou a aba **[Releases](../../releases)**, é o
> caminho certo pra instalar.

Pré-requisito: o **Google Chrome** precisa já estar instalado no computador
(usado como reforço contra bloqueio anti-robô nas buscas).

O programa confere sozinho, toda vez que abre, se saiu uma versão nova
aqui no GitHub — e avisa, com um clique pra atualizar.

---

## O que ele faz

- Você escolhe uma categoria (Processador, Placa Mãe, Memória RAM, Placa de
  Vídeo, SSD, Fonte, Gabinete, Water Cooler, Monitor) e busca um produto.
- Ele varre **KaBuM!, Pichau, Terabyte Shop, Amazon.com.br e Mercado Livre**
  de uma vez e mostra os preços encontrados, com link para cada loja — já
  filtrando produtos que não têm a ver com o que você buscou (veja
  "Filtro de relevância" abaixo).
- Você adiciona o item à lista da categoria. Toda vez que você clicar em
  **"Atualizar preços"**, ele busca de novo e guarda no histórico.
- Na lista, cada item aparece em **verde** se o preço mais recente é mais
  barato do que ele já esteve, e em **vermelho** se está mais caro do que já
  esteve.
- Em **"Montar PC"**, você cria um PC, e para cada categoria (processador,
  placa mãe, memória, etc.) escolhe uma peça da sua lista. O app busca o
  preço atual dela e soma tudo no rodapé. Ao clicar em **"Finalizar
  orçamento"**, o total fica salvo — da próxima vez que você recalcular, ele
  mostra se o PC completo ficou mais barato ou mais caro que da última vez
  (mesmo esquema verde/vermelho).

## Rodando a partir do código-fonte (pra quem quer programar/alterar o app)

Você precisa do **Python 3.10+** instalado (verifique com `python --version`
no terminal do VSCode).

Abra a pasta do projeto no VSCode, abra um terminal (`` Ctrl+` ``) e rode:

```bash
pip install -r requirements.txt
```

Isso instala `requests`, `beautifulsoup4` e `curl_cffi` (essenciais — sem o
`curl_cffi` várias lojas voltam a tomar bloqueio 403). O `selenium` também
está na lista e é **fortemente recomendado**: é ele quem resolve os casos em
que mesmo o `curl_cffi` é bloqueado, e é obrigatório para a KaBuM! (veja a
seção 3).

## 2. Rodando o programa

```bash
python main.py
```

Uma janela vai abrir. Na primeira vez que você adicionar um produto, o
programa cria sozinho um arquivo `precos.db` (SQLite) na mesma pasta —
é aí que fica todo o seu histórico. Não precisa configurar nada.

## 3. Como o app evita ser bloqueado pelas lojas (anti-bloqueio)

Lojas grandes (principalmente **Amazon**, **Mercado Livre** e **KaBuM!**)
usam proteções anti-robô que bloqueiam requisições "cruas", mesmo com
cabeçalhos de navegador — foi exatamente o erro `403 Client Error: Forbidden`
que você viu antes.

Para cada loja, o `scraper.py` tenta, em ordem, e **para assim que uma
camada trouxer resultados**:

1. **`curl_cffi`** — faz a requisição imitando o "footprint" TLS/HTTP de um
   Chrome de verdade. Resolve a maior parte dos bloqueios 403 sem precisar
   abrir navegador nenhum (rápido).
2. **`requests`** — uma sessão "aquecida" (visita a home da loja antes da
   busca, para ganhar cookies) com cabeçalhos completos de navegador.
3. **Selenium (Chrome headless)** — abre um Chrome de verdade, invisível, só
   quando as duas camadas acima falham. É o mais lento, mas é praticamente
   indistinguível de um usuário real. **A KaBuM! quase sempre precisa desta
   camada**, porque ela monta a lista de produtos via JavaScript depois que
   a página abre — uma busca simples não vê nada dela.

Para o Selenium funcionar:

1. Tenha o **Google Chrome** instalado no seu PC (você quase certamente já
   tem).
2. Já está no `requirements.txt` — `pip install -r requirements.txt` resolve.
3. Não precisa baixar "chromedriver" manualmente, o Selenium moderno (4.6+)
   baixa e gerencia isso sozinho na primeira execução.

Se você preferir não usar Selenium/Chrome, abra `config.py` e mude:

```python
USAR_SELENIUM_FALLBACK = False
```

O app continua funcionando, só que quando `curl_cffi`/`requests` forem
bloqueados por alguma loja, ela pode voltar com 0 resultados naquela busca.

**Amazon e Mercado Livre são as lojas mais difíceis de garantir 100% do
tempo** — são sites gigantes com proteção anti-robô muito agressiva (podem
mostrar CAPTCHA de vez em quando mesmo para navegadores reais). O app foi
feito para tentar da forma mais robusta possível, mas não há garantia
absoluta — se uma busca vier vazia só nessas duas, tente de novo em alguns
minutos.

## 4. Filtro de relevância (evita produtos que você não pediu)

As lojas costumam devolver, junto dos resultados de busca, produtos de
seções de "relacionados", "categoria inteira" ou "quem viu este também viu".
Foi isso que causou o problema de buscar "RTX 5060" e receber RX 7600, RTX
3050 etc.

Agora, todo produto extraído passa pela função `eh_relevante` (em
`scraper.py`): ele só é mantido se o título contiver os mesmos números do
termo buscado (ex.: "5700x", "5060", "850w" precisam aparecer no título,
palavra por palavra) e a maior parte das outras palavras do termo também.

Se notar resultados **errados demais**, aumente `LIMIAR_RELEVANCIA` em
`config.py` (ex.: para `0.7`). Se notar que está vindo **pouca coisa**
(algumas lojas escrevem o nome de um jeito bem diferente), diminua (ex.:
para `0.3`), ou simplifique o termo de busca — evite código de fabricante,
prefira "Ryzen 7 5700X" a "Ryzen 7 5700X 100-100000926WOF".

## 5. Se uma loja "quebrar" no futuro

Sites de loja mudam o layout de vez em quando, e um scraper pode parar de
achar produtos. Para depurar rapidamente, rode direto o `scraper.py` pelo
terminal, sem abrir a interface:

```bash
python scraper.py "Ryzen 7 5700X"
```

Isso imprime, loja por loja: qual camada (curl_cffi / requests / Selenium)
foi usada, se alguma bloqueou (403 ou parecido), quantos produtos foram
encontrados e a lista completa com preços e links. Se uma loja voltar com 0
resultados:

1. Abra o site da loja no navegador, faça a mesma busca, e aperte
   `Ctrl+U` (ver código-fonte) ou F12 → aba "Elements".
2. Veja se a estrutura mudou (nome de classes, se os produtos aparecem no
   HTML inicial ou só depois de rolar a página).
3. Ajuste a função correspondente em `scraper.py` (`buscar_pichau`,
   `buscar_terabyte`, `buscar_kabum`, `buscar_amazon`,
   `buscar_mercadolivre`). Cada uma é independente das outras, então mexer
   em uma não quebra as demais.

## 6. Adicionando outra loja

Em `scraper.py`, copie o padrão de `buscar_terabyte` (é o mais simples) para
uma nova função `buscar_minhaloja(termo, max_resultados=10, driver_selenium=None)`,
ajuste a URL de busca e o `contem_no_href` (um trecho que sempre aparece no
link de um produto daquela loja, tipo `/produto/` ou `/p/`), e chame
`_buscar_com_camadas(...)` como as outras já fazem — isso já dá acesso
automático ao anti-bloqueio em camadas. Depois adicione a loja em duas
listas:

```python
# scraper.py
BUSCADORES = {
    "KaBuM!": buscar_kabum,
    "Pichau": buscar_pichau,
    "Terabyte Shop": buscar_terabyte,
    "Amazon.com.br": buscar_amazon,
    "Mercado Livre": buscar_mercadolivre,
    "Minha Loja": buscar_minhaloja,   # <- nova linha
}
```

```python
# config.py
LOJAS_DISPONIVEIS = [
    "KaBuM!", "Pichau", "Terabyte Shop", "Amazon.com.br", "Mercado Livre",
    "Minha Loja",
]
```

## 7. Estrutura dos arquivos

| Arquivo         | O que faz |
|-----------------|-----------|
| `config.py`     | Categorias, lojas, timeouts, filtro de relevância — ajustes gerais |
| `database.py`   | Tudo relacionado ao SQLite (produtos, histórico, PCs montados) |
| `scraper.py`    | Busca os produtos nas lojas, com anti-bloqueio em camadas e filtro de relevância (pode rodar sozinho pelo terminal) |
| `main.py`       | Interface gráfica (Tkinter) — é o que você executa |
| `precos.db`     | Criado automaticamente na primeira busca — seu histórico fica aqui |

## 8. Limitações a saber

- Scraping depende do site não ter mudado e não estar bloqueando robôs. O
  app tenta várias camadas para contornar isso, mas nenhuma técnica é 100%
  garantida para sempre — sites de anti-bot evoluem. Evite rodar buscas em
  loop muito rápido (o app já espera um pouco entre lojas de propósito).
- O preço "final" extraído é o valor à vista/PIX mostrado no card do
  produto — pode não bater 100% com o preço no carrinho (frete, cupom etc.
  não entram na conta).
- O filtro de relevância reduz bastante produtos errados, mas não é
  perfeito — títulos muito diferentes do termo buscado (ex.: abreviações
  incomuns de uma loja específica) podem escapar ou ser descartados demais;
  ajuste `LIMIAR_RELEVANCIA` se precisar.
- O app é de uso pessoal/local — os dados ficam só no seu computador, no
  arquivo `precos.db`.
