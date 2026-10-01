# -*- coding: utf-8 -*-
"""
Rastreador de Preços — Black Friday
Ponto de entrada da aplicação (interface gráfica em Tkinter).

Rode com:  python main.py
"""

import os
import queue
import subprocess
import sys
import textwrap
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import datetime, timedelta
from tkinter import messagebox, simpledialog, ttk

# Rodando como .exe congelado (instalado via o instalador): llm_config.py e
# email_config.py ficam de fora do pacote de propósito (continuam editáveis
# como arquivo de texto comum do lado do .exe, sem precisar recompilar pra
# trocar uma chave/senha) — sem isso no sys.path, `import llm_config`
# (dentro de llm.py) e `import email_config` (dentro de notificacoes.py)
# quebrariam na hora de abrir o programa.
if getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(sys.executable))

import database as db
import llm
import notificacoes
import rotinas as rotinas_mod
from config import (
    BASE_DIR, CATEGORIAS, LOJAS_DISPONIVEIS, LOJAS_ELETRO_MOVEIS, ORDEM_CATEGORIAS, ORDEM_CATEGORIAS_CASA,
)
from scraper import buscar_em_todas_as_lojas, buscar_produto_por_url

NOME_TAREFA_AGENDADA = "ZandonadiRadar_Rotinas"


def _caminho_checador():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rotina_checador.py")


def _caminho_pythonw():
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def _comando_tarefa_agendada():
    """
    Comando que a Tarefa Agendada do Windows roda a cada 15 minutos. Rodando
    de código-fonte (`python main.py`), é o pythonw.exe chamando
    rotina_checador.py direto. Já "congelado" (instalado via o instalador,
    sem Python separado), não existe um rotina_checador.py solto pra
    chamar — o próprio .exe principal já leva esse código embutido, então a
    tarefa roda o mesmo .exe com um argumento especial (ver main(), lá
    embaixo) que faz ele rodar só a checagem, sem abrir a janela.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --rotina-checador'
    return f'"{_caminho_pythonw()}" "{_caminho_checador()}"'


def garantir_tarefa_agendada():
    """
    Cria (ou atualiza) uma Tarefa Agendada do Windows que roda o checador de
    rotinas a cada 15 minutos, mesmo com o programa fechado. Silenciosa se
    falhar (ex.: não é Windows, ou schtasks sem permissão) — nesse caso as
    rotinas só rodam enquanto o app estiver aberto não, ficam só salvas.
    """
    if sys.platform != "win32":
        return False
    comando = _comando_tarefa_agendada()
    try:
        resultado = subprocess.run(
            ["schtasks", "/create", "/tn", NOME_TAREFA_AGENDADA, "/tr", comando,
             "/sc", "minute", "/mo", "15", "/f"],
            capture_output=True, text=True, timeout=15,
        )
        return resultado.returncode == 0
    except Exception:
        return False


def remover_tarefa_agendada():
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", NOME_TAREFA_AGENDADA, "/f"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        pass


def tarefa_agendada_existe():
    if sys.platform != "win32":
        return False
    try:
        resultado = subprocess.run(
            ["schtasks", "/query", "/tn", NOME_TAREFA_AGENDADA],
            capture_output=True, text=True, timeout=10,
        )
        return resultado.returncode == 0
    except Exception:
        return False

if sys.platform == "win32":
    # Sem isso, o Windows agrupa a barra de tarefas pelo AppUserModelID de
    # python.exe e mostra o ícone do Python em vez do ícone da janela.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZandonadiRadar.App")
    except Exception:
        pass

# Paleta: fundo escuro, laranja como cor de ação/destaque (mesmo estilo do
# resumo de ofertas). Ícone e nome do app continuam os mesmos de antes.
COR_ACCENT = "#ff6b3d"
COR_ACCENT_ESCURO = "#d9541f"
COR_ACCENT_CLARO = "#ffa06b"

COR_VERDE = "#3ecf8e"
COR_VERDE_CHIP_BG = "#17301f"
COR_VERMELHO = "#ff6b6b"
COR_VERMELHO_CHIP_BG = "#3a1f22"
COR_NEUTRO = "#8b93a3"

COR_FUNDO = "#14171c"
COR_CARD_BG = "#1b1f26"
COR_CARD_BORDA = "#2c313d"
COR_RODAPE_BG = "#1f242e"

COR_TEXTO = "#eaeef4"
COR_TEXTO_MUTED = "#8b93a3"
COR_TEXTO_FRACO = "#5b6270"

COR_FUNDO_SIDEBAR = "#0f1115"
COR_FUNDO_SIDEBAR_HOVER = "#1a1e25"
COR_SIDEBAR_DIVISOR = "#22262e"
COR_SIDEBAR_TEXTO = "#c7ccd6"
COR_SIDEBAR_TEXTO_FRACO = "#6b7280"

FONTE_TITULO = "Bahnschrift SemiBold"
FONTE_MONO = "Consolas"

ICON_PATH = os.path.join(BASE_DIR, "icone.ico")
ICON_PNG_PATH = os.path.join(BASE_DIR, "icone.png")


def formatar_preco(valor):
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "§").replace(".", ",").replace("§", ".")
    return f"R$ {texto}"


class BotaoArredondado:
    """
    Botão "de verdade" — cantos arredondados + sombra (efeito 3D) — desenhado
    num Canvas, porque o tk.Button nativo do Windows não sabe fazer nem uma
    coisa nem outra. Expõe pack/grid/config parecido com tk.Button pra poder
    substituir os botões antigos sem mexer em quem os usa.
    """
    RAIO = 10
    SOMBRA = 3

    _ESTILOS = {
        "primario": dict(
            bg=COR_ACCENT, fg="#1a1108", hover=COR_ACCENT_ESCURO, sombra="#0a0b0e",
            desabilitado="#5a4635", fg_desabilitado="#8b8378",
        ),
        "secundario": dict(
            bg=COR_CARD_BORDA, fg=COR_TEXTO, hover="#3a4152", sombra="#0a0b0e",
            desabilitado="#22262e", fg_desabilitado="#5b6270",
        ),
        "perigo": dict(
            bg="#b3392b", fg="#fff5f2", hover="#8f2c21", sombra="#0a0b0e",
            desabilitado="#3a2624", fg_desabilitado="#8a6a67",
        ),
    }

    def __init__(self, parent, texto, comando=None, estilo="primario", font_size=10, padx=16, pady=9):
        self._cores = self._ESTILOS.get(estilo, self._ESTILOS["primario"])
        self.comando = comando
        self._texto = texto
        self._font = tkfont.Font(family="Segoe UI", size=font_size, weight="bold")
        self._padx = padx
        self._pady = pady
        self._estado = "normal"
        self._hover = False

        self.canvas = tk.Canvas(parent, highlightthickness=0, bd=0, bg=self._cor_fundo(parent))
        self._recalcular_tamanho()

        self.canvas.bind("<Enter>", self._ao_entrar)
        self.canvas.bind("<Leave>", self._ao_sair)
        self.canvas.bind("<Button-1>", self._ao_clicar)

    @staticmethod
    def _cor_fundo(parent):
        try:
            return parent.cget("bg")
        except tk.TclError:
            return COR_FUNDO

    def _recalcular_tamanho(self):
        largura_texto = max(self._font.measure(self._texto), 1)
        altura_texto = self._font.metrics("linespace")
        self._largura = largura_texto + self._padx * 2 + self.SOMBRA
        self._altura = altura_texto + self._pady * 2 + self.SOMBRA
        self.canvas.config(width=self._largura, height=self._altura)
        self._desenhar()

    @staticmethod
    def _pontos_arredondados(x1, y1, x2, y2, r):
        r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        return [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]

    def _desenhar(self):
        self.canvas.delete("all")
        w, h = self._largura, self._altura
        face_w, face_h = w - self.SOMBRA, h - self.SOMBRA
        desabilitado = self._estado == "disabled"

        if not desabilitado:
            pts_sombra = self._pontos_arredondados(self.SOMBRA, self.SOMBRA, w, h, self.RAIO)
            self.canvas.create_polygon(pts_sombra, smooth=True, fill=self._cores["sombra"], outline="")

        if desabilitado:
            cor_face = self._cores["desabilitado"]
        elif self._hover:
            cor_face = self._cores["hover"]
        else:
            cor_face = self._cores["bg"]
        pts_face = self._pontos_arredondados(0, 0, face_w, face_h, self.RAIO)
        self.canvas.create_polygon(pts_face, smooth=True, fill=cor_face, outline="")

        cor_texto = self._cores["fg_desabilitado"] if desabilitado else self._cores["fg"]
        self.canvas.create_text(face_w / 2, face_h / 2, text=self._texto, fill=cor_texto, font=self._font)
        self.canvas.config(cursor="arrow" if desabilitado else "hand2")

    def _ao_entrar(self, event=None):
        if self._estado != "disabled":
            self._hover = True
            self._desenhar()

    def _ao_sair(self, event=None):
        self._hover = False
        self._desenhar()

    def _ao_clicar(self, event=None):
        if self._estado != "disabled" and self.comando:
            self.comando()

    # -- interface parecida com tk.Button, pra servir de substituto --
    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self

    def grid(self, **kw):
        self.canvas.grid(**kw)
        return self

    def pack_forget(self):
        self.canvas.pack_forget()

    def config(self, **kw):
        if "command" in kw:
            self.comando = kw.pop("command")
        if "state" in kw:
            self._estado = kw.pop("state")
        if "text" in kw and kw["text"] != self._texto:
            self._texto = kw.pop("text")
            self._recalcular_tamanho()
            return
        self._desenhar()

    configure = config

    def cget(self, key):
        if key == "state":
            return self._estado
        if key == "text":
            return self._texto
        return None


def criar_botao(parent, texto, comando=None, estilo="primario", font_size=10):
    return BotaoArredondado(parent, texto, comando=comando, estilo=estilo, font_size=font_size)


def criar_entry(parent, **kw):
    return tk.Entry(
        parent, bg=COR_CARD_BG, fg=COR_TEXTO, insertbackground=COR_TEXTO,
        relief="flat", highlightthickness=1, highlightbackground=COR_CARD_BORDA,
        highlightcolor=COR_ACCENT, font=("Segoe UI", 10), **kw
    )


def texto_selecionavel(parent, texto, font, fg, bg=None, largura_chars=None, padx=0, pady=0):
    """
    Como um tk.Label, mas o texto pode ser selecionado com o mouse e copiado
    com Ctrl+C (ou botão direito → Copiar) — um Label comum do Tkinter não
    deixa fazer isso. Usado pra nomes de produto, preços, títulos encontrados
    etc., onde é útil poder copiar o texto exato pra colar em outro lugar.

    Sem `largura_chars`: uma linha só, do tamanho exato do texto (pra preço,
    nome de loja, chip de variação etc.). Com `largura_chars`: quebra em
    várias linhas nessa largura (pra nomes de produto compridos) — a altura
    é calculada já de cara a partir do texto (`textwrap`), sem depender da
    janela já estar desenhada na tela (contar linhas depois de desenhado dá
    altura errada/gigante se o widget ainda não foi "mapeado").
    """
    bg = bg or COR_CARD_BG
    if largura_chars is None:
        largura, altura, wrap = max(1, len(texto)), 1, "none"
    else:
        linhas = textwrap.wrap(texto, width=largura_chars) or [""]
        largura, altura, wrap = largura_chars, max(1, len(linhas)), "word"

    caixa = tk.Text(
        parent, font=font, fg=fg, bg=bg, bd=0, highlightthickness=0,
        wrap=wrap, width=largura, height=altura, padx=padx, pady=pady,
        cursor="xterm", insertwidth=0,
    )
    caixa.insert("1.0", texto)
    caixa.configure(state="disabled")

    menu_contexto = tk.Menu(caixa, tearoff=0, bg=COR_CARD_BG, fg=COR_TEXTO, activebackground=COR_ACCENT, activeforeground="#1a1108")
    menu_contexto.add_command(label="📋 Copiar", command=lambda: (caixa.clipboard_clear(), caixa.clipboard_append(texto)))
    caixa.bind("<Button-3>", lambda e: menu_contexto.tk_popup(e.x_root, e.y_root))

    return caixa


class RastreadorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Zandonadi Radar")
        self.configure(bg=COR_FUNDO)
        try:
            self.iconbitmap(default=ICON_PATH)
        except Exception:
            pass
        try:
            self._icone_taskbar = tk.PhotoImage(file=ICON_PNG_PATH)
            self.iconphoto(True, self._icone_taskbar)
        except Exception:
            pass
        self.geometry("1150x680")
        self.minsize(950, 600)
        self._configurar_estilo_ttk()

        self.fila_eventos = queue.Queue()
        self.after(100, self._processar_fila)

        self._icone_bandeja = None
        self._avisou_bandeja = False
        self.protocol("WM_DELETE_WINDOW", self._minimizar_para_bandeja)
        self._configurar_bandeja()

        # Estado da busca em segundo plano: sobrevive à troca de tela — se o
        # usuário sair de "Buscar produto" enquanto ela roda, a thread
        # continua e só reflete na tela quando ele voltar pra lá.
        self._tela_ativa = None
        self._categoria_ativa = None
        self._busca = {
            "ativo": False, "termo": "", "categoria_chave": None,
            "evento": None, "status": "", "resultados": None,
        }
        self._busca_widgets = {}
        self._rotinas_em_execucao = set()

        self._montar_layout()
        self.mostrar_boas_vindas()
        self.after(5000, self._checar_rotinas_em_segundo_plano)

    def _checar_rotinas_em_segundo_plano(self):
        """
        Reforço além da Tarefa Agendada do Windows: enquanto o app estiver
        aberto, confere a cada minuto se alguma rotina está na hora de
        rodar. Roda em silêncio (sem abrir janela) — se quiser acompanhar,
        use "▶ Rodar agora" na tela de Rotinas.
        """
        try:
            agora = datetime.now()
            for rotina in db.listar_rotinas():
                if rotina["id"] in self._rotinas_em_execucao:
                    continue
                horario = rotinas_mod.horario_pendente(rotina, agora)
                if horario is not None:
                    self._rotinas_em_execucao.add(rotina["id"])

                    def trabalho(r=rotina, h=horario):
                        try:
                            rotinas_mod.executar_rotina(r, horario=h)
                        finally:
                            self.fila_eventos.put(lambda: self._rotinas_em_execucao.discard(r["id"]))
                            if self._tela_ativa == "rotinas":
                                self.fila_eventos.put(self.mostrar_rotinas)

                    threading.Thread(target=trabalho, daemon=True).start()
        except Exception:
            pass
        self.after(60000, self._checar_rotinas_em_segundo_plano)

    def _configurar_estilo_ttk(self):
        """
        Os widgets ttk (Treeview, Combobox, Scrollbar, Progressbar) não
        seguem as cores tk normais — sem isso eles ficam com o tema claro
        padrão do Windows, destoando do resto da tela escura.
        """
        estilo = ttk.Style(self)
        estilo.theme_use("clam")

        estilo.configure(
            "Treeview", background=COR_CARD_BG, fieldbackground=COR_CARD_BG,
            foreground=COR_TEXTO, bordercolor=COR_CARD_BORDA, borderwidth=0, rowheight=26,
        )
        estilo.map(
            "Treeview",
            background=[("selected", COR_ACCENT)],
            foreground=[("selected", "#1a1108")],
        )
        estilo.configure(
            "Treeview.Heading", background=COR_RODAPE_BG, foreground=COR_TEXTO_MUTED,
            relief="flat", font=("Segoe UI", 9, "bold"), borderwidth=0,
        )
        estilo.map("Treeview.Heading", background=[("active", COR_CARD_BORDA)])

        estilo.configure(
            "TCombobox", fieldbackground=COR_CARD_BG, background=COR_CARD_BG,
            foreground=COR_TEXTO, arrowcolor=COR_TEXTO_MUTED, bordercolor=COR_CARD_BORDA,
            lightcolor=COR_CARD_BG, darkcolor=COR_CARD_BG, borderwidth=1,
        )
        estilo.map(
            "TCombobox",
            fieldbackground=[("readonly", COR_CARD_BG)],
            foreground=[("readonly", COR_TEXTO)],
            background=[("readonly", COR_CARD_BG)],
        )
        self.option_add("*TCombobox*Listbox.background", COR_CARD_BG)
        self.option_add("*TCombobox*Listbox.foreground", COR_TEXTO)
        self.option_add("*TCombobox*Listbox.selectBackground", COR_ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "#1a1108")

        estilo.configure(
            "Vertical.TScrollbar", background=COR_CARD_BORDA, troughcolor=COR_FUNDO,
            bordercolor=COR_FUNDO, arrowcolor=COR_TEXTO_MUTED,
        )
        estilo.map("Vertical.TScrollbar", background=[("active", COR_ACCENT)])

        estilo.configure(
            "TProgressbar", background=COR_ACCENT, troughcolor=COR_CARD_BG,
            bordercolor=COR_CARD_BG, lightcolor=COR_ACCENT, darkcolor=COR_ACCENT,
        )

    # ------------------------------------------------------------------
    # Bandeja do sistema — fechar no X minimiza pra lá em vez de encerrar;
    # fecha de verdade só pelo menu (botão direito no ícone) → "Fechar".
    # ------------------------------------------------------------------
    def _configurar_bandeja(self):
        try:
            import pystray
            from PIL import Image
        except ImportError:
            return  # sem pystray/Pillow instalado — X fecha o app normalmente

        try:
            imagem = Image.open(ICON_PNG_PATH)
        except Exception:
            return

        def ao_abrir(icone, item):
            self.fila_eventos.put(self._restaurar_janela)

        def ao_fechar(icone, item):
            icone.stop()
            self.fila_eventos.put(self.destroy)

        menu = pystray.Menu(
            pystray.MenuItem("Abrir Zandonadi Radar", ao_abrir, default=True),
            pystray.MenuItem("Fechar", ao_fechar),
        )
        self._icone_bandeja = pystray.Icon("ZandonadiRadar", imagem, "Zandonadi Radar", menu)
        threading.Thread(target=self._icone_bandeja.run, daemon=True).start()

    def _restaurar_janela(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _minimizar_para_bandeja(self):
        if self._icone_bandeja is None:
            # Sem bandeja disponível (pystray não instalado) — X fecha mesmo.
            self.destroy()
            return
        self.withdraw()
        if not self._avisou_bandeja:
            self._avisou_bandeja = True
            try:
                self._icone_bandeja.notify(
                    "O Zandonadi Radar continua rodando aqui. Clique com o botão direito "
                    "no ícone e escolha “Fechar” pra encerrar de verdade.",
                    "Zandonadi Radar",
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Layout geral: sidebar fixa + área de conteúdo que troca de tela
    # ------------------------------------------------------------------
    def _montar_layout(self):
        container = tk.Frame(self)
        container.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(container, bg=COR_FUNDO_SIDEBAR, width=230)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        titulo = tk.Label(
            self.sidebar, text="📡 Zandonadi\nRadar", bg=COR_FUNDO_SIDEBAR,
            fg=COR_ACCENT, font=(FONTE_TITULO, 16, "bold"), justify="left", anchor="w", pady=18, padx=14
        )
        titulo.pack(fill="x")

        tk.Frame(self.sidebar, bg=COR_SIDEBAR_DIVISOR, height=1).pack(fill="x", padx=10, pady=(0, 8))

        self._botao_sidebar("🔎  Buscar produto", self.mostrar_busca, destaque=True)
        self._botao_sidebar("🔗  Adicionar por link", self.mostrar_adicionar_link, destaque=True)
        self._botao_sidebar("🛠️  Montar PC", self.mostrar_montagem, destaque=True)
        self._botao_sidebar("⏰  Rotinas", self.mostrar_rotinas, destaque=True)

        tk.Frame(self.sidebar, bg=COR_SIDEBAR_DIVISOR, height=1).pack(fill="x", padx=10, pady=8)

        # Categorias (PC + casa) ficam numa área rolável à parte — só isso,
        # não o menu principal acima — porque a lista já não cabe inteira
        # numa janela pequena.
        area_categorias = tk.Frame(self.sidebar, bg=COR_FUNDO_SIDEBAR)
        area_categorias.pack(fill="both", expand=True)

        canvas_cat = tk.Canvas(area_categorias, bg=COR_FUNDO_SIDEBAR, highlightthickness=0)
        scrollbar_cat = ttk.Scrollbar(area_categorias, orient="vertical", command=canvas_cat.yview)
        lista_cat = tk.Frame(canvas_cat, bg=COR_FUNDO_SIDEBAR)
        lista_cat.bind("<Configure>", lambda e: canvas_cat.configure(scrollregion=canvas_cat.bbox("all")))
        canvas_cat.create_window((0, 0), window=lista_cat, anchor="nw", width=1)
        canvas_cat.configure(yscrollcommand=scrollbar_cat.set)
        canvas_cat.bind("<Configure>", lambda e: canvas_cat.itemconfig(1, width=e.width))
        canvas_cat.pack(side="left", fill="both", expand=True)
        scrollbar_cat.pack(side="right", fill="y")

        def _rolar_categorias(event):
            canvas_cat.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas_cat.bind("<Enter>", lambda e: canvas_cat.bind_all("<MouseWheel>", _rolar_categorias))
        canvas_cat.bind("<Leave>", lambda e: canvas_cat.unbind_all("<MouseWheel>"))

        tk.Label(
            lista_cat, text="CATEGORIAS (PC)", bg=COR_FUNDO_SIDEBAR, fg=COR_SIDEBAR_TEXTO_FRACO,
            font=("Segoe UI", 9, "bold"), anchor="w", padx=14
        ).pack(fill="x", pady=(2, 4))
        for chave in ORDEM_CATEGORIAS:
            rotulo = CATEGORIAS[chave]
            self._botao_sidebar(rotulo, lambda c=chave: self.mostrar_categoria(c), parent=lista_cat)

        tk.Frame(lista_cat, bg=COR_SIDEBAR_DIVISOR, height=1).pack(fill="x", padx=10, pady=8)
        tk.Label(
            lista_cat, text="ELETRODOMÉSTICOS E MÓVEIS", bg=COR_FUNDO_SIDEBAR, fg=COR_SIDEBAR_TEXTO_FRACO,
            font=("Segoe UI", 9, "bold"), anchor="w", padx=14, wraplength=195, justify="left",
        ).pack(fill="x", pady=(2, 4))
        for chave in ORDEM_CATEGORIAS_CASA:
            rotulo = CATEGORIAS[chave]
            self._botao_sidebar(rotulo, lambda c=chave: self.mostrar_categoria(c), parent=lista_cat)

        self.area_conteudo = tk.Frame(container, bg=COR_FUNDO)
        self.area_conteudo.pack(side="left", fill="both", expand=True)

    def _botao_sidebar(self, texto, comando, destaque=False, parent=None):
        parent = parent or self.sidebar
        cor_texto = COR_ACCENT_CLARO if destaque else COR_SIDEBAR_TEXTO
        btn = tk.Label(
            parent, text=texto, bg=COR_FUNDO_SIDEBAR, fg=cor_texto,
            font=("Segoe UI", 10, "bold" if destaque else "normal"),
            anchor="w", padx=18, pady=8, cursor="hand2"
        )
        btn.pack(fill="x")
        btn.bind("<Enter>", lambda e: btn.config(bg=COR_FUNDO_SIDEBAR_HOVER))
        btn.bind("<Leave>", lambda e: btn.config(bg=COR_FUNDO_SIDEBAR))
        btn.bind("<Button-1>", lambda e: comando())
        return btn

    def _limpar_conteudo(self):
        for widget in self.area_conteudo.winfo_children():
            widget.destroy()

    def _processar_fila(self):
        try:
            while True:
                funcao = self.fila_eventos.get_nowait()
                try:
                    funcao()
                except tk.TclError:
                    pass  # widget da tela que originou o evento já não existe mais
        except queue.Empty:
            pass
        self.after(100, self._processar_fila)

    def _status_preco_resultado(self, resultado):
        """
        'verde' se esse preço é o mais barato já visto para essa URL exata,
        'vermelho' se é o mais caro já visto, 'neutro' se é a primeira vez
        (ou empatou). Usado para colorir os resultados de uma busca antes
        mesmo de o item ser adicionado à lista.
        """
        hist = db.historico_por_url(resultado.get("url"))
        if not hist:
            return "neutro"
        precos_anteriores = [h["preco"] for h in hist]
        preco = resultado["preco"]
        if preco < min(precos_anteriores) - 0.01:
            return "verde"
        if preco > max(precos_anteriores) + 0.01:
            return "vermelho"
        return "neutro"

    # ------------------------------------------------------------------
    # Tela inicial
    # ------------------------------------------------------------------
    def mostrar_boas_vindas(self):
        self._limpar_conteudo()
        self._tela_ativa = "boas_vindas"
        frame = tk.Frame(self.area_conteudo, bg=COR_FUNDO)
        frame.pack(expand=True)
        tk.Label(
            frame, text="Bem-vindo! 👋", font=(FONTE_TITULO, 28, "bold"), bg=COR_FUNDO, fg=COR_TEXTO
        ).pack(pady=(0, 10))
        tk.Label(
            frame,
            text="Use “Buscar produto” para acompanhar um item, ou\n"
                 "escolha uma categoria no menu para ver o que você já cadastrou.",
            font=("Segoe UI", 11), bg=COR_FUNDO, fg=COR_TEXTO_MUTED, justify="center"
        ).pack()

    # ==================================================================
    # TELA: Buscar produto
    # ==================================================================
    def mostrar_busca(self, categoria_pre_selecionada=None):
        self._limpar_conteudo()
        self._tela_ativa = "busca"
        frame = self.area_conteudo

        tk.Label(frame, text="Buscar produto", font=(FONTE_TITULO, 22, "bold"), bg=COR_FUNDO, fg=COR_TEXTO).pack(
            anchor="w", padx=20, pady=(18, 6)
        )

        linha_busca = tk.Frame(frame, bg=COR_FUNDO)
        linha_busca.pack(fill="x", padx=20, pady=6)

        tk.Label(linha_busca, text="O que procurar:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED).grid(row=0, column=0, sticky="w")
        entry_termo = criar_entry(linha_busca, width=55)
        entry_termo.grid(row=1, column=0, sticky="w", pady=4, ipady=3)
        entry_termo.focus()

        tk.Label(linha_busca, text="Categoria:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED).grid(row=0, column=1, sticky="w", padx=(16, 0))
        combo_categoria = ttk.Combobox(
            linha_busca, values=list(CATEGORIAS.values()), state="readonly", width=22
        )
        combo_categoria.grid(row=1, column=1, sticky="w", padx=(16, 0))
        if categoria_pre_selecionada and categoria_pre_selecionada in CATEGORIAS:
            combo_categoria.set(CATEGORIAS[categoria_pre_selecionada])
        else:
            combo_categoria.current(0)

        btn_buscar = criar_botao(linha_busca, "Buscar nas lojas", estilo="primario")
        btn_buscar.grid(row=1, column=2, padx=(16, 0))

        btn_parar = criar_botao(linha_busca, "🛑 Parar", estilo="perigo")
        btn_parar.grid(row=1, column=3, padx=(8, 0))
        btn_parar.config(state="disabled")

        linha_sugestao = tk.Frame(frame, bg=COR_CARD_BG, highlightbackground=COR_CARD_BORDA, highlightthickness=1)
        label_sugestao = tk.Label(
            linha_sugestao, text="", bg=COR_CARD_BG, fg=COR_TEXTO, font=("Segoe UI", 9),
            wraplength=560, justify="left",
        )
        label_sugestao.pack(side="left", padx=(12, 8), pady=8)
        btn_sugestao_sim = criar_botao(linha_sugestao, "Sim, usar", estilo="primario", font_size=9)
        btn_sugestao_sim.pack(side="left", padx=4, pady=8)
        btn_sugestao_nao = criar_botao(linha_sugestao, "Não, manter", estilo="secundario", font_size=9)
        btn_sugestao_nao.pack(side="left", padx=4, pady=8)

        status_var = tk.StringVar(value="")
        label_status = tk.Label(frame, textvariable=status_var, bg=COR_FUNDO, fg=COR_TEXTO_MUTED)
        label_status.pack(anchor="w", padx=20)

        # área de resultados (Treeview)
        colunas = ("loja", "titulo", "preco")
        tree = ttk.Treeview(frame, columns=colunas, show="headings", height=16, selectmode="extended")
        tree.heading("loja", text="Loja")
        tree.heading("titulo", text="Produto")
        tree.heading("preco", text="Preço")
        tree.column("loja", width=110, anchor="w")
        tree.column("titulo", width=650, anchor="w")
        tree.column("preco", width=110, anchor="e")
        tree.pack(fill="both", expand=True, padx=20, pady=10)
        tree.tag_configure("verde", foreground=COR_VERDE)
        tree.tag_configure("vermelho", foreground=COR_VERMELHO)
        tree.tag_configure("neutro", foreground=COR_NEUTRO)

        resultados_atuais = {"lista": list(self._busca.get("resultados") or [])}

        def linha_selecionada():
            sel = tree.selection()
            if not sel:
                return None
            idx = tree.index(sel[0])
            return resultados_atuais["lista"][idx]

        def abrir_link(event=None):
            item = linha_selecionada()
            if item:
                webbrowser.open(item["url"])

        tree.bind("<Double-1>", abrir_link)

        barra_inferior = tk.Frame(frame, bg=COR_FUNDO)
        barra_inferior.pack(fill="x", padx=20, pady=(0, 16))
        tk.Label(
            barra_inferior,
            text="Dica: dê 2 cliques pra abrir o link da loja. Selecione uma ou mais linhas (Ctrl/Shift) "
                 "pra adicionar só elas. Verde/vermelho = mais barato/mais caro do que já esteve.",
            bg=COR_FUNDO, fg=COR_TEXTO_FRACO, font=("Segoe UI", 9), wraplength=650, justify="left",
        ).pack(side="left")

        btn_adicionar = criar_botao(barra_inferior, "➕ Adicionar tudo como 1 produto", estilo="primario")
        btn_adicionar.config(state="disabled")
        btn_adicionar.pack(side="right")

        btn_adicionar_selecao = criar_botao(barra_inferior, "➕ Adicionar selecionado(s)", estilo="secundario")
        btn_adicionar_selecao.config(state="disabled")
        btn_adicionar_selecao.pack(side="right", padx=(0, 8))

        def _ao_mudar_selecao(event=None):
            btn_adicionar_selecao.config(state="normal" if tree.selection() else "disabled")

        tree.bind("<<TreeviewSelect>>", _ao_mudar_selecao)

        # Registra os widgets atuais para que a busca em segundo plano (ou já
        # em andamento de antes de o usuário sair e voltar a essa tela)
        # consiga refletir aqui.
        self._busca_widgets = {
            "status_var": status_var, "tree": tree, "btn_buscar": btn_buscar,
            "btn_parar": btn_parar, "btn_adicionar": btn_adicionar,
            "resultados_atuais": resultados_atuais,
        }

        def _preencher_resultados(resultados):
            tree.delete(*tree.get_children())
            for r in resultados:
                tree.insert(
                    "", "end", values=(r["loja"], r["titulo"], formatar_preco(r["preco"])),
                    tags=(self._status_preco_resultado(r),),
                )

        if self._busca["ativo"]:
            # já tinha uma busca rodando (começada antes de sair dessa tela)
            entry_termo.delete(0, "end")
            entry_termo.insert(0, self._busca["termo"])
            if self._busca["categoria_chave"] in CATEGORIAS:
                combo_categoria.set(CATEGORIAS[self._busca["categoria_chave"]])
            status_var.set(self._busca["status"])
            btn_buscar.config(state="disabled", text="Buscando...")
            btn_parar.config(state="normal")
        elif self._busca["resultados"] is not None:
            # busca anterior já terminou — mostra o que encontrou
            entry_termo.delete(0, "end")
            entry_termo.insert(0, self._busca["termo"])
            if self._busca["categoria_chave"] in CATEGORIAS:
                combo_categoria.set(CATEGORIAS[self._busca["categoria_chave"]])
            status_var.set(self._busca["status"])
            _preencher_resultados(resultados_atuais["lista"])
            btn_adicionar.config(state="normal" if resultados_atuais["lista"] else "disabled")

        def esconder_sugestao():
            linha_sugestao.pack_forget()

        def _disparar_busca(termo):
            esconder_sugestao()
            categoria_rotulo = combo_categoria.get()
            categoria_chave = [k for k, v in CATEGORIAS.items() if v == categoria_rotulo][0]

            evento = threading.Event()
            self._busca.update(
                ativo=True, termo=termo, categoria_chave=categoria_chave,
                evento=evento, status="Buscando nas lojas, aguarde...", resultados=None,
            )

            btn_buscar.config(state="disabled", text="Buscando...")
            btn_parar.config(state="normal")
            btn_adicionar.config(state="disabled")
            tree.delete(*tree.get_children())
            status_var.set("Buscando nas lojas, aguarde...")

            def trabalho():
                lojas = LOJAS_ELETRO_MOVEIS if categoria_chave == "eletrodomesticos_moveis" else LOJAS_DISPONIVEIS
                resultados = buscar_em_todas_as_lojas(
                    termo, lojas=lojas,
                    callback_progresso=lambda loja, st: self.fila_eventos.put(
                        lambda: self._progresso_busca(loja, st)
                    ),
                    cancelar_evento=evento,
                )
                self.fila_eventos.put(lambda: self._finalizar_busca(termo, categoria_chave, resultados, evento))

            threading.Thread(target=trabalho, daemon=True).start()

        def usar_sugestao(termo_sugerido):
            entry_termo.delete(0, "end")
            entry_termo.insert(0, termo_sugerido)
            _disparar_busca(termo_sugerido)

        btn_sugestao_nao.config(command=lambda: _disparar_busca(entry_termo.get().strip()))

        def executar_busca():
            termo = entry_termo.get().strip()
            if not termo:
                messagebox.showwarning("Atenção", "Digite o que você quer buscar.")
                return
            esconder_sugestao()

            if not llm.esta_configurado():
                _disparar_busca(termo)
                return

            # Antes de gastar tempo buscando em 5 lojas, o LLM (se ativado)
            # confere rapidinho se dá pra sugerir um termo mais objetivo —
            # só interrompe se achar algo melhor de verdade.
            btn_buscar.config(state="disabled", text="Pensando...")

            def trabalho():
                sugestao = llm.sugerir_melhoria_termo_llm(termo)

                def finalizar():
                    btn_buscar.config(state="normal", text="Buscar nas lojas")
                    if not sugestao:
                        _disparar_busca(termo)
                        return
                    label_sugestao.config(
                        text=f"💡 Sugestão do assistente: buscar por “{sugestao}” em vez de “{termo}”?"
                    )
                    btn_sugestao_sim.config(command=lambda: usar_sugestao(sugestao))
                    linha_sugestao.pack(fill="x", padx=20, pady=(0, 10), before=label_status)

                self.fila_eventos.put(finalizar)

            threading.Thread(target=trabalho, daemon=True).start()

        btn_buscar.config(command=executar_busca)
        btn_parar.config(command=self._parar_busca_ativa)
        entry_termo.bind("<Return>", lambda e: executar_busca())

        def adicionar_a_lista():
            termo = entry_termo.get().strip()
            categoria_rotulo = combo_categoria.get()
            categoria_chave = [k for k, v in CATEGORIAS.items() if v == categoria_rotulo][0]
            if not resultados_atuais["lista"]:
                return

            nome_sugerido = termo
            nome = simpledialog.askstring(
                "Nome do produto",
                "Como você quer chamar esse item na sua lista?",
                initialvalue=nome_sugerido,
                parent=self,
            )
            if not nome:
                return

            produto_id = db.adicionar_produto(categoria_chave, nome, termo)
            db.registrar_precos(produto_id, resultados_atuais["lista"])
            messagebox.showinfo(
                "Adicionado!",
                f"“{nome}” foi adicionado em {CATEGORIAS[categoria_chave]}.\n"
                f"{len(resultados_atuais['lista'])} preços salvos no histórico."
            )
            self.mostrar_categoria(categoria_chave)

        btn_adicionar.config(command=adicionar_a_lista)

        def adicionar_selecionados():
            selecionados = tree.selection()
            if not selecionados:
                return
            categoria_rotulo = combo_categoria.get()
            categoria_chave = [k for k, v in CATEGORIAS.items() if v == categoria_rotulo][0]
            itens = [resultados_atuais["lista"][tree.index(s)] for s in selecionados]

            nomes_adicionados = []
            for item in itens:
                nome = item["titulo"][:80]
                produto_id = db.adicionar_produto(
                    categoria_chave, nome, item["url"], modo="url", url_fixa=item["url"]
                )
                db.registrar_precos(produto_id, [item])
                nomes_adicionados.append(nome)

            messagebox.showinfo(
                "Adicionado!",
                f"{len(nomes_adicionados)} item(ns) adicionado(s) em {CATEGORIAS[categoria_chave]}, "
                f"cada um como produto separado:\n\n" + "\n".join(f"• {n}" for n in nomes_adicionados)
            )
            self.mostrar_categoria(categoria_chave)

        btn_adicionar_selecao.config(command=adicionar_selecionados)

    def _progresso_busca(self, loja, status_loja):
        """Chamado (via fila) a cada loja processada por uma busca em segundo plano."""
        texto = f"[{loja}] {status_loja}"
        self._busca["status"] = texto
        if self._tela_ativa != "busca":
            return
        status_var = self._busca_widgets.get("status_var")
        if status_var is not None:
            status_var.set(texto)

    def _finalizar_busca(self, termo, categoria_chave, resultados, evento):
        """Chamado (via fila) quando uma busca em segundo plano termina."""
        if evento.is_set():
            return  # foi cancelada — _parar_busca_ativa() já cuidou da UI
        if resultados:
            status_texto = f"{len(resultados)} resultado(s) encontrado(s) para “{termo}”."
        else:
            status_texto = (
                "Nenhum resultado encontrado. Tente um termo mais simples "
                "(ex.: sem o código do fabricante) ou verifique sua internet."
            )
        self._busca.update(ativo=False, evento=None, resultados=resultados, status=status_texto)

        if self._tela_ativa != "busca":
            return  # usuário está em outra tela — os dados ficam prontos pra quando ele voltar
        w = self._busca_widgets
        tree = w.get("tree")
        if tree is None:
            return
        w["resultados_atuais"]["lista"] = resultados
        tree.delete(*tree.get_children())
        for r in resultados:
            tree.insert(
                "", "end", values=(r["loja"], r["titulo"], formatar_preco(r["preco"])),
                tags=(self._status_preco_resultado(r),),
            )
        w["status_var"].set(status_texto)
        w["btn_adicionar"].config(state="normal" if resultados else "disabled")
        w["btn_buscar"].config(state="normal", text="Buscar nas lojas")
        w["btn_parar"].config(state="disabled")

    def _parar_busca_ativa(self):
        """Cancela a busca em segundo plano, esteja o usuário nessa tela ou não."""
        evento = self._busca.get("evento")
        if evento is None:
            return
        evento.set()
        self._busca.update(ativo=False, evento=None, status="Busca cancelada.")
        if self._tela_ativa != "busca":
            return
        w = self._busca_widgets
        w["status_var"].set("Busca cancelada.")
        w["btn_buscar"].config(state="normal", text="Buscar nas lojas")
        w["btn_parar"].config(state="disabled")

    # ==================================================================
    # TELA: Adicionar produto por link direto
    # ==================================================================
    def mostrar_adicionar_link(self, categoria_pre_selecionada=None):
        self._limpar_conteudo()
        self._tela_ativa = "adicionar_link"
        frame = self.area_conteudo

        tk.Label(
            frame, text="Adicionar produto por link", font=(FONTE_TITULO, 22, "bold"), bg=COR_FUNDO, fg=COR_TEXTO
        ).pack(anchor="w", padx=20, pady=(18, 6))
        tk.Label(
            frame,
            text="Cole o link da página do produto (KaBuM!, Pichau, Terabyte Shop, Amazon ou Mercado Livre).",
            bg=COR_FUNDO, fg=COR_TEXTO_MUTED,
        ).pack(anchor="w", padx=20)

        linha = tk.Frame(frame, bg=COR_FUNDO)
        linha.pack(fill="x", padx=20, pady=10)

        tk.Label(linha, text="Link do produto:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED).grid(row=0, column=0, sticky="w")
        entry_url = criar_entry(linha, width=70)
        entry_url.grid(row=1, column=0, sticky="w", pady=4, ipady=3)
        entry_url.focus()

        tk.Label(linha, text="Categoria:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED).grid(row=0, column=1, sticky="w", padx=(16, 0))
        combo_categoria = ttk.Combobox(linha, values=list(CATEGORIAS.values()), state="readonly", width=22)
        combo_categoria.grid(row=1, column=1, sticky="w", padx=(16, 0))
        if categoria_pre_selecionada and categoria_pre_selecionada in CATEGORIAS:
            combo_categoria.set(CATEGORIAS[categoria_pre_selecionada])
        else:
            combo_categoria.current(0)

        btn_verificar = criar_botao(linha, "🔍 Verificar link", estilo="primario")
        btn_verificar.grid(row=1, column=2, padx=(16, 0))

        status_var = tk.StringVar(value="")
        tk.Label(frame, textvariable=status_var, bg=COR_FUNDO, fg=COR_TEXTO_MUTED).pack(anchor="w", padx=20, pady=(4, 0))

        resultado_caixa = tk.Frame(frame, bg=COR_CARD_BG, highlightbackground=COR_CARD_BORDA, highlightthickness=1)
        label_titulo_encontrado = tk.Label(
            resultado_caixa, text="", bg=COR_CARD_BG, fg=COR_TEXTO, font=("Segoe UI", 11, "bold"),
            wraplength=820, justify="left",
        )
        label_titulo_encontrado.pack(anchor="w", padx=14, pady=(12, 2))
        label_preco_encontrado = tk.Label(
            resultado_caixa, text="", bg=COR_CARD_BG, fg=COR_ACCENT, font=(FONTE_MONO, 15, "bold")
        )
        label_preco_encontrado.pack(anchor="w", padx=14, pady=(0, 12))

        linha_nome = tk.Frame(frame, bg=COR_FUNDO)
        tk.Label(linha_nome, text="Nome para salvar na lista:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED).grid(row=0, column=0, sticky="w")
        entry_nome = criar_entry(linha_nome, width=55)
        entry_nome.grid(row=1, column=0, sticky="w", pady=4, ipady=3)
        btn_adicionar = criar_botao(linha_nome, "➕ Adicionar à lista da categoria", estilo="primario")
        btn_adicionar.grid(row=1, column=1, padx=(16, 0))

        resultado_atual = {"item": None}

        def verificar():
            url = entry_url.get().strip()
            if not url:
                messagebox.showwarning("Atenção", "Cole o link do produto.")
                return
            if not url.startswith("http"):
                messagebox.showwarning("Atenção", "Isso não parece um link válido.")
                return

            resultado_atual["item"] = None
            resultado_caixa.pack_forget()
            linha_nome.pack_forget()
            btn_verificar.config(state="disabled", text="Verificando...")
            status_var.set("Lendo a página do produto, aguarde (pode demorar um pouco)...")

            def progresso(loja, st):
                self.fila_eventos.put(lambda: status_var.set(f"[{loja}] {st}"))

            def trabalho():
                resultados = buscar_produto_por_url(url, callback_progresso=progresso)

                def finalizar():
                    btn_verificar.config(state="normal", text="🔍 Verificar link")
                    if not resultados:
                        status_var.set(
                            "Não consegui ler um preço nesse link. Confira se é a página de um "
                            "produto (não de busca/categoria) e tente de novo."
                        )
                        return
                    item = resultados[0]
                    resultado_atual["item"] = item
                    status_var.set(f"Encontrado na {item['loja']}.")
                    label_titulo_encontrado.config(text=item["titulo"])
                    label_preco_encontrado.config(text=formatar_preco(item["preco"]))
                    resultado_caixa.pack(fill="x", padx=20, pady=10)
                    entry_nome.delete(0, "end")
                    entry_nome.insert(0, item["titulo"][:70])
                    linha_nome.pack(fill="x", padx=20, pady=(0, 16))

                self.fila_eventos.put(finalizar)

            threading.Thread(target=trabalho, daemon=True).start()

        btn_verificar.config(command=verificar)
        entry_url.bind("<Return>", lambda e: verificar())

        def adicionar():
            item = resultado_atual["item"]
            if not item:
                return
            categoria_rotulo = combo_categoria.get()
            categoria_chave = [k for k, v in CATEGORIAS.items() if v == categoria_rotulo][0]
            nome = entry_nome.get().strip() or item["titulo"]

            produto_id = db.adicionar_produto(categoria_chave, nome, item["url"], modo="url", url_fixa=item["url"])
            db.registrar_precos(produto_id, [item])
            messagebox.showinfo(
                "Adicionado!",
                f"“{nome}” foi adicionado em {CATEGORIAS[categoria_chave]}.\n"
                f"Use “🔄 Atualizar preços” na lista pra conferir a variação desse mesmo link depois."
            )
            self.mostrar_categoria(categoria_chave)

        btn_adicionar.config(command=adicionar)

    # ==================================================================
    # TELA: Categoria (lista de produtos rastreados)
    # ==================================================================
    def mostrar_categoria(self, categoria_chave):
        self._limpar_conteudo()
        self._tela_ativa = "categoria"
        self._categoria_ativa = categoria_chave
        frame = self.area_conteudo
        rotulo = CATEGORIAS[categoria_chave]

        topo = tk.Frame(frame, bg=COR_FUNDO)
        topo.pack(fill="x", padx=20, pady=(18, 6))
        tk.Label(topo, text=rotulo, font=(FONTE_TITULO, 22, "bold"), bg=COR_FUNDO, fg=COR_TEXTO).pack(side="left")
        criar_botao(
            topo, "🔗 Adicionar por link",
            lambda: self.mostrar_adicionar_link(categoria_chave), estilo="secundario"
        ).pack(side="right", padx=(8, 0))
        criar_botao(
            topo, "🔎 Buscar novo item nesta categoria",
            lambda: self._buscar_para_categoria(categoria_chave), estilo="secundario"
        ).pack(side="right")

        produtos = db.listar_produtos(categoria_chave)

        if not produtos:
            tk.Label(
                frame, text="Você ainda não tem nenhum item cadastrado nesta categoria.",
                bg=COR_FUNDO, fg=COR_TEXTO_MUTED, font=("Segoe UI", 11)
            ).pack(padx=20, pady=30, anchor="w")
            return

        cont = tk.Frame(frame, bg=COR_FUNDO)
        cont.pack(fill="both", expand=True, padx=20, pady=6)

        canvas = tk.Canvas(cont, bg=COR_FUNDO, highlightthickness=0)
        scrollbar = ttk.Scrollbar(cont, orient="vertical", command=canvas.yview)
        lista_frame = tk.Frame(canvas, bg=COR_FUNDO)

        lista_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=lista_frame, anchor="nw", width=1)
        canvas.configure(yscrollcommand=scrollbar.set)

        def ajustar_largura(event):
            canvas.itemconfig(1, width=event.width)

        canvas.bind("<Configure>", ajustar_largura)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for produto in produtos:
            self._linha_produto(lista_frame, produto, categoria_chave)

    def _linha_produto(self, container, produto, categoria_chave):
        variacao = db.variacao_preco(produto["id"])
        melhor = db.melhor_preco_atual(produto["id"])

        card = tk.Frame(container, bg=COR_CARD_BG, highlightbackground=COR_CARD_BORDA, highlightthickness=1)
        card.pack(fill="x", pady=5, padx=2)

        esquerda = tk.Frame(card, bg=COR_CARD_BG)
        esquerda.pack(side="left", fill="both", expand=True, padx=14, pady=10)

        linha_nome = tk.Frame(esquerda, bg=COR_CARD_BG)
        linha_nome.pack(anchor="w", fill="x")
        texto_selecionavel(
            linha_nome, produto["nome"], font=("Segoe UI", 11, "bold"), fg=COR_TEXTO, largura_chars=48,
        ).pack(side="left")
        if produto.get("modo") == "url" and produto.get("url_fixa"):
            link_lbl = tk.Label(
                linha_nome, text="🔗 link direto", font=("Segoe UI", 8, "underline"),
                bg=COR_CARD_BG, fg=COR_ACCENT, cursor="hand2",
            )
            link_lbl.pack(side="left", padx=(8, 0))
            link_lbl.bind("<Button-1>", lambda e, u=produto["url_fixa"]: webbrowser.open(u))

        if melhor:
            linha_preco = tk.Frame(esquerda, bg=COR_CARD_BG)
            linha_preco.pack(anchor="w", pady=(4, 0))

            texto_selecionavel(
                linha_preco, formatar_preco(melhor["preco"]), font=(FONTE_MONO, 14, "bold"), fg=COR_TEXTO,
            ).pack(side="left")
            texto_selecionavel(
                linha_preco, f"  na {melhor['loja']}", font=("Segoe UI", 9), fg=COR_TEXTO_MUTED,
            ).pack(side="left")

            pct = None
            if variacao and variacao.get("anterior_min"):
                pct = abs(variacao["diferenca"]) / variacao["anterior_min"] * 100

            if variacao and variacao["status"] == "verde":
                chip_bg, chip_fg = COR_VERDE_CHIP_BG, COR_VERDE
                chip_texto = f"▼ {pct:.0f}% mais barato" if pct is not None else "▼ mais barato que já esteve"
            elif variacao and variacao["status"] == "vermelho":
                chip_bg, chip_fg = COR_VERMELHO_CHIP_BG, COR_VERMELHO
                chip_texto = f"▲ {pct:.0f}% mais caro" if pct is not None else "▲ mais caro que já esteve"
            else:
                chip_bg, chip_fg, chip_texto = None, COR_TEXTO_FRACO, "primeira vez / preço estável"

            if chip_bg:
                texto_selecionavel(
                    linha_preco, chip_texto, font=(FONTE_MONO, 9, "bold"), fg=chip_fg, bg=chip_bg,
                    padx=6, pady=1,
                ).pack(side="left", padx=(8, 0))
            else:
                texto_selecionavel(
                    linha_preco, chip_texto, font=("Segoe UI", 9), fg=chip_fg,
                ).pack(side="left", padx=(8, 0))
        else:
            tk.Label(esquerda, text="Sem preços registrados ainda.", bg=COR_CARD_BG, fg=COR_TEXTO_FRACO).pack(anchor="w")

        direita = tk.Frame(card, bg=COR_CARD_BG)
        direita.pack(side="right", padx=14, pady=10)

        criar_botao(
            direita, "🔄 Atualizar preços",
            lambda: self._atualizar_precos_produto(produto, categoria_chave), estilo="primario"
        ).pack(side="left", padx=4)
        criar_botao(
            direita, "📈 Histórico",
            lambda: self._mostrar_historico(produto), estilo="secundario"
        ).pack(side="left", padx=4)
        criar_botao(
            direita, "🗑️",
            lambda: self._remover_produto(produto, categoria_chave), estilo="perigo"
        ).pack(side="left", padx=4)

    def _remover_produto(self, produto, categoria_chave):
        if messagebox.askyesno("Remover", f"Remover “{produto['nome']}” da sua lista?"):
            db.remover_produto(produto["id"])
            self.mostrar_categoria(categoria_chave)

    def _atualizar_precos_produto(self, produto, categoria_chave):
        eh_url = produto.get("modo") == "url" and produto.get("url_fixa")
        descricao = produto["url_fixa"] if eh_url else produto["termo_busca"]

        janela = tk.Toplevel(self, bg=COR_FUNDO)
        janela.title("Atualizando preços...")
        janela.geometry("400x150")
        janela.resizable(False, False)
        tk.Label(
            janela, text=f"{'Lendo' if eh_url else 'Buscando'} “{descricao}”...", pady=10, wraplength=360,
            bg=COR_FUNDO, fg=COR_TEXTO,
        ).pack()
        status_var = tk.StringVar(value="Iniciando...")
        tk.Label(janela, textvariable=status_var, bg=COR_FUNDO, fg=COR_TEXTO_MUTED).pack()
        barra = ttk.Progressbar(janela, mode="indeterminate")
        barra.pack(fill="x", padx=20, pady=10)
        barra.start(12)

        evento = threading.Event()

        def parar():
            evento.set()
            status_var.set("Cancelando...")
            btn_parar.config(state="disabled")

        btn_parar = criar_botao(janela, "🛑 Parar", parar, estilo="perigo")
        btn_parar.pack(pady=(0, 8))

        def progresso(loja, status_loja):
            self.fila_eventos.put(lambda: status_var.set(f"[{loja}] {status_loja}"))

        def trabalho():
            if eh_url:
                resultados = buscar_produto_por_url(produto["url_fixa"], callback_progresso=progresso)
            else:
                lojas = LOJAS_ELETRO_MOVEIS if categoria_chave == "eletrodomesticos_moveis" else LOJAS_DISPONIVEIS
                resultados = buscar_em_todas_as_lojas(
                    produto["termo_busca"], lojas=lojas, callback_progresso=progresso,
                    cancelar_evento=evento,
                )

            def finalizar():
                janela.destroy()
                if evento.is_set():
                    return
                if resultados:
                    db.registrar_precos(produto["id"], resultados)
                if self._tela_ativa == "categoria" and self._categoria_ativa == categoria_chave:
                    self.mostrar_categoria(categoria_chave)
                if not resultados:
                    messagebox.showwarning(
                        "Sem resultados", "Não encontramos preços novos agora. Tente novamente mais tarde."
                    )

            self.fila_eventos.put(finalizar)

        threading.Thread(target=trabalho, daemon=True).start()

    def _mostrar_historico(self, produto):
        janela = tk.Toplevel(self, bg=COR_FUNDO)
        janela.title(f"Histórico — {produto['nome']}")
        janela.geometry("700x580")

        hist = db.historico_produto(produto["id"])
        if not hist:
            tk.Label(janela, text="Sem histórico ainda.", pady=20, bg=COR_FUNDO, fg=COR_TEXTO_MUTED).pack()
            return

        # --- gráfico: menor preço de cada lote de busca, ao longo do tempo ---
        lotes = {}
        for h in hist:
            data = h["buscado_em"]
            if data not in lotes or h["preco"] < lotes[data]:
                lotes[data] = h["preco"]
        pontos = sorted(lotes.items())

        if len(pontos) >= 2:
            try:
                from matplotlib.figure import Figure
                from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
                import matplotlib.dates as mdates
                from datetime import datetime as _dt

                datas = [_dt.strptime(d, "%Y-%m-%d %H:%M:%S") for d, _ in pontos]
                precos = [p for _, p in pontos]

                fig = Figure(figsize=(6.6, 2.8), dpi=100)
                fig.patch.set_facecolor(COR_FUNDO)
                ax = fig.add_subplot(111)
                ax.set_facecolor(COR_CARD_BG)
                ax.plot(datas, precos, marker="o", color=COR_ACCENT, linewidth=2, markersize=4)

                # Rotular TODO ponto vira ilegível quando há muitos próximos
                # no tempo/preço (texto empilhado em cima do outro) — em vez
                # disso, só os pontos que realmente contam pra entender a
                # variação: primeiro, último, menor e maior preço do período.
                indices_destaque = sorted({0, len(precos) - 1, precos.index(min(precos)), precos.index(max(precos))})
                for i, idx in enumerate(indices_destaque):
                    offset_y = 11 if i % 2 == 0 else -15
                    ax.annotate(
                        formatar_preco(precos[idx]), (datas[idx], precos[idx]),
                        textcoords="offset points", xytext=(0, offset_y),
                        fontsize=8, ha="center", va="bottom" if offset_y > 0 else "top", color=COR_TEXTO,
                        bbox=dict(boxstyle="round,pad=0.2", fc=COR_CARD_BG, ec="none", alpha=0.85),
                    )
                ax.set_title("Variação do menor preço encontrado", fontsize=10, color=COR_TEXTO)
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
                fig.autofmt_xdate(rotation=25)
                ax.grid(True, alpha=0.25, color=COR_TEXTO_MUTED)
                ax.margins(y=0.25)
                ax.tick_params(colors=COR_TEXTO_MUTED, labelsize=8)
                for spine in ax.spines.values():
                    spine.set_color(COR_CARD_BORDA)
                fig.tight_layout()

                canvas_grafico = FigureCanvasTkAgg(fig, master=janela)
                canvas_grafico.draw()
                canvas_grafico.get_tk_widget().pack(fill="x", padx=10, pady=(10, 0))
            except ImportError:
                tk.Label(
                    janela, bg=COR_FUNDO, fg=COR_TEXTO_FRACO,
                    text="Instale 'matplotlib' (pip install matplotlib) para ver o gráfico de variação."
                ).pack(pady=4)
        elif len(pontos) == 1:
            tk.Label(
                janela, bg=COR_FUNDO, fg=COR_TEXTO_FRACO,
                text="Só há uma busca registrada ainda — atualize os preços de novo para ver o gráfico."
            ).pack(pady=8)

        tk.Label(
            janela,
            text="Dê duplo clique numa linha pra abrir o anúncio no navegador. "
                 "Clique com o botão direito pra copiar o link ou o título.",
            bg=COR_FUNDO, fg=COR_TEXTO_FRACO, font=("Segoe UI", 8), wraplength=660, justify="left",
        ).pack(fill="x", padx=10, pady=(0, 2))

        colunas = ("data", "loja", "preco", "titulo")
        tree = ttk.Treeview(janela, columns=colunas, show="headings")
        tree.heading("data", text="Buscado em")
        tree.heading("loja", text="Loja")
        tree.heading("preco", text="Preço")
        tree.heading("titulo", text="Título encontrado")
        tree.column("data", width=130)
        tree.column("loja", width=100)
        tree.column("preco", width=90, anchor="e")
        tree.column("titulo", width=280)
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        for h in hist:
            tree.insert("", "end", values=(h["buscado_em"], h["loja"], formatar_preco(h["preco"]), h["titulo"]))

        def _copiar_para_area_transferencia(texto):
            if not texto:
                return
            janela.clipboard_clear()
            janela.clipboard_append(texto)

        def _abrir_url(h):
            url = h.get("url")
            if url:
                webbrowser.open(url)
            else:
                messagebox.showinfo("Sem link", "Esse registro não tem um link salvo.", parent=janela)

        def _abrir_url_selecionada(event=None):
            sel = tree.selection()
            if not sel:
                return
            _abrir_url(hist[tree.index(sel[0])])

        tree.bind("<Double-1>", _abrir_url_selecionada)

        menu_contexto = tk.Menu(
            janela, tearoff=0, bg=COR_CARD_BG, fg=COR_TEXTO,
            activebackground=COR_ACCENT, activeforeground="#1a1108",
        )

        def _mostrar_menu_contexto(event):
            iid = tree.identify_row(event.y)
            if not iid:
                return
            tree.selection_set(iid)
            h = hist[tree.index(iid)]
            menu_contexto.delete(0, "end")
            menu_contexto.add_command(label="🔗 Abrir no navegador", command=lambda: _abrir_url(h))
            menu_contexto.add_command(
                label="📋 Copiar link", command=lambda: _copiar_para_area_transferencia(h.get("url"))
            )
            menu_contexto.add_command(
                label="📋 Copiar título", command=lambda: _copiar_para_area_transferencia(h.get("titulo"))
            )
            menu_contexto.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", _mostrar_menu_contexto)

    def _buscar_para_categoria(self, categoria_chave):
        self.mostrar_busca(categoria_chave)

    # ==================================================================
    # TELA: Montar PC
    # ==================================================================
    def mostrar_montagem(self):
        self._limpar_conteudo()
        self._tela_ativa = "montagem"
        frame = self.area_conteudo

        topo = tk.Frame(frame, bg=COR_FUNDO)
        topo.pack(fill="x", padx=20, pady=(18, 10))
        tk.Label(topo, text="Montar PC", font=(FONTE_TITULO, 22, "bold"), bg=COR_FUNDO, fg=COR_TEXTO).pack(side="left")

        builds = db.listar_builds()
        combo_builds = ttk.Combobox(
            topo, values=[f"{b['id']} — {b['nome']}" for b in builds], state="readonly", width=35
        )
        combo_builds.pack(side="left", padx=12)
        if builds:
            combo_builds.current(0)

        def novo_build():
            nome = simpledialog.askstring("Novo PC", "Nome para este PC (ex: 'Setup Black Friday'):", parent=self)
            if nome:
                build_id = db.criar_build(nome)
                self.mostrar_montagem()

        criar_botao(topo, "➕ Novo PC", novo_build, estilo="primario").pack(side="left")

        def excluir_build():
            if not builds:
                return
            idx = combo_builds.current()
            if idx < 0:
                return
            build_id = builds[idx]["id"]
            if messagebox.askyesno("Excluir", "Excluir este PC e seus itens?"):
                db.remover_build(build_id)
                self.mostrar_montagem()

        criar_botao(topo, "🗑️ Excluir PC", excluir_build, estilo="perigo").pack(side="left", padx=6)

        def ver_grafico():
            idx = combo_builds.current()
            if idx < 0:
                return
            self._mostrar_grafico_build(builds[idx])

        criar_botao(topo, "📊 Gráfico", ver_grafico, estilo="secundario").pack(side="left")

        if not builds:
            tk.Label(
                frame, text="Crie um PC para começar a montar (“➕ Novo PC”).",
                bg=COR_FUNDO, fg=COR_TEXTO_MUTED, font=("Segoe UI", 11)
            ).pack(padx=20, pady=30, anchor="w")
            return

        idx = combo_builds.current() if combo_builds.current() >= 0 else 0
        build = builds[idx]

        def trocar_build(event=None):
            i = combo_builds.current()
            if i >= 0:
                self._desenhar_build(frame, builds[i])

        combo_builds.bind("<<ComboboxSelected>>", trocar_build)

        self._desenhar_build(frame, build)

    def _desenhar_build(self, frame_pai, build):
        # remove tudo abaixo da barra de topo (mantém o topo)
        filhos = frame_pai.winfo_children()
        for w in filhos[1:]:
            w.destroy()

        itens = db.listar_itens_build(build["id"])

        area = tk.Frame(frame_pai, bg=COR_FUNDO)
        area.pack(fill="both", expand=True, padx=20, pady=6)

        canvas = tk.Canvas(area, bg=COR_FUNDO, highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        lista_frame = tk.Frame(canvas, bg=COR_FUNDO)
        lista_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=lista_frame, anchor="nw", width=1)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(1, width=e.width))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for categoria_chave in ORDEM_CATEGORIAS:
            self._slot_build(lista_frame, build, categoria_chave, itens.get(categoria_chave))

        # ---- rodapé: total ----
        rodape = tk.Frame(frame_pai, bg=COR_RODAPE_BG, highlightbackground=COR_CARD_BORDA, highlightthickness=1)
        rodape.pack(fill="x", padx=20, pady=(6, 16))

        itens_atualizados = db.listar_itens_build(build["id"])
        preenchidos = [i for i in itens_atualizados.values() if i.get("preco")]
        faltando = len(ORDEM_CATEGORIAS) - len(preenchidos)
        total = sum(i["preco"] for i in preenchidos)

        esquerda = tk.Frame(rodape, bg=COR_RODAPE_BG)
        esquerda.pack(side="left", padx=16, pady=12)
        tk.Label(
            esquerda, text=f"{len(preenchidos)}/{len(ORDEM_CATEGORIAS)} peças selecionadas"
                            + (f"  ·  faltam {faltando}" if faltando else "  ·  completo!"),
            bg=COR_RODAPE_BG, fg=COR_TEXTO_MUTED
        ).pack(anchor="w")

        cor_total = COR_TEXTO
        texto_var = ""
        if preenchidos:
            variacao = db.variacao_total_build(build["id"], total)
            if variacao["status"] == "verde":
                cor_total = COR_VERDE
                texto_var = "▼ mais barato que da última vez"
            elif variacao["status"] == "vermelho":
                cor_total = COR_VERMELHO
                texto_var = "▲ mais caro que da última vez"

        linha_total = tk.Frame(esquerda, bg=COR_RODAPE_BG)
        linha_total.pack(anchor="w", pady=(4, 0))
        tk.Label(linha_total, text="Total:", font=("Segoe UI", 10), bg=COR_RODAPE_BG, fg=COR_TEXTO_MUTED).pack(side="left")
        tk.Label(
            linha_total, text=formatar_preco(total), font=(FONTE_MONO, 19, "bold"),
            bg=COR_RODAPE_BG, fg=cor_total,
        ).pack(side="left", padx=(6, 0))
        if texto_var:
            tk.Label(
                linha_total, text=texto_var, font=("Segoe UI", 10), bg=COR_RODAPE_BG, fg=cor_total
            ).pack(side="left", padx=(8, 0))

        def finalizar():
            if not preenchidos:
                messagebox.showwarning("Atenção", "Selecione ao menos uma peça antes de finalizar.")
                return
            db.registrar_total_build(build["id"], total)
            messagebox.showinfo(
                "Orçamento salvo!",
                f"Total de {formatar_preco(total)} salvo no histórico deste PC.\n"
                f"Na próxima vez que você recalcular, vamos comparar com este valor."
            )
            self.mostrar_montagem()

        criar_botao(
            rodape, "✅ Finalizar / Recalcular orçamento", finalizar, estilo="primario"
        ).pack(side="right", padx=16, pady=12)

        criar_botao(
            rodape, "🔄 Recalcular preços de todas as peças",
            lambda: self._recalcular_precos_build(build), estilo="secundario"
        ).pack(side="right", padx=(0, 4), pady=12)

    def _recalcular_precos_build(self, build):
        """
        Busca de novo o preço de CADA peça já selecionada nesse PC (não só
        soma o que já está salvo) — útil pra saber se o orçamento inteiro
        ficou mais barato ou mais caro sem ter que atualizar peça por peça.
        """
        itens = db.listar_itens_build(build["id"])
        alvos = [(cat, item) for cat, item in itens.items() if item.get("produto_id")]
        if not alvos:
            messagebox.showinfo(
                "Nada para recalcular", "Esse PC ainda não tem nenhuma peça selecionada."
            )
            return

        janela = tk.Toplevel(self, bg=COR_FUNDO)
        janela.title("Recalculando preços do PC...")
        janela.geometry("420x160")
        janela.resizable(False, False)
        tk.Label(
            janela, text=f"Atualizando {len(alvos)} peça(s) de “{build['nome']}”...",
            pady=10, wraplength=380, bg=COR_FUNDO, fg=COR_TEXTO,
        ).pack()
        status_var = tk.StringVar(value="Iniciando...")
        tk.Label(
            janela, textvariable=status_var, bg=COR_FUNDO, fg=COR_TEXTO_MUTED, wraplength=380
        ).pack()
        barra = ttk.Progressbar(janela, mode="determinate", maximum=len(alvos))
        barra.pack(fill="x", padx=20, pady=10)

        evento = threading.Event()

        def parar():
            evento.set()
            status_var.set("Cancelando...")
            btn_parar.config(state="disabled")

        btn_parar = criar_botao(janela, "🛑 Parar", parar, estilo="perigo")
        btn_parar.pack(pady=(0, 8))

        def trabalho():
            for i, (categoria_chave, item) in enumerate(alvos, start=1):
                if evento.is_set():
                    break
                produto = db.obter_produto(item["produto_id"])
                if not produto:
                    continue

                nome_exibicao = produto["nome"]
                self.fila_eventos.put(
                    lambda n=nome_exibicao, i=i: status_var.set(f"({i}/{len(alvos)}) {n}...")
                )

                if produto.get("modo") == "url" and produto.get("url_fixa"):
                    resultados = buscar_produto_por_url(produto["url_fixa"])
                else:
                    resultados = buscar_em_todas_as_lojas(
                        produto["termo_busca"], lojas=LOJAS_DISPONIVEIS, cancelar_evento=evento,
                    )

                if resultados:
                    db.registrar_precos(produto["id"], resultados)
                    melhor = min(resultados, key=lambda r: r["preco"])
                    db.definir_item_build(
                        build["id"], categoria_chave, produto["id"],
                        melhor.get("loja"), melhor.get("titulo") or produto["nome"],
                        melhor["preco"], melhor.get("url", "")
                    )

                self.fila_eventos.put(lambda i=i: barra.config(value=i))

            def finalizar_recalculo():
                janela.destroy()
                if self._tela_ativa == "montagem":
                    self.mostrar_montagem()

            self.fila_eventos.put(finalizar_recalculo)

        threading.Thread(target=trabalho, daemon=True).start()

    def _mostrar_grafico_build(self, build):
        """
        Gráfico do PC: evolução do total (quando há pelo menos 2 orçamentos
        salvos com "Finalizar") + quais peças ficaram mais caras/baratas
        desde a última vez que os preços foram checados.
        """
        janela = tk.Toplevel(self, bg=COR_FUNDO)
        janela.title(f"Gráfico — {build['nome']}")
        janela.geometry("780x680")

        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import matplotlib.dates as mdates
            from datetime import datetime as _dt
        except ImportError:
            tk.Label(
                janela, bg=COR_FUNDO, fg=COR_TEXTO_FRACO, pady=30,
                text="Instale 'matplotlib' (pip install matplotlib) para ver o gráfico.",
            ).pack()
            return

        def _estilizar_eixo(ax):
            ax.tick_params(colors=COR_TEXTO_MUTED, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(COR_CARD_BORDA)

        # A quantidade de peças varia (até 9 categorias) e o 2º gráfico cresce
        # com elas — sem rolagem, conteúdo comprido ficava cortado na janela.
        area = tk.Frame(janela, bg=COR_FUNDO)
        area.pack(fill="both", expand=True)
        canvas_rolagem = tk.Canvas(area, bg=COR_FUNDO, highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=canvas_rolagem.yview)
        conteudo = tk.Frame(canvas_rolagem, bg=COR_FUNDO)
        conteudo.bind("<Configure>", lambda e: canvas_rolagem.configure(scrollregion=canvas_rolagem.bbox("all")))
        canvas_rolagem.create_window((0, 0), window=conteudo, anchor="nw", width=1)
        canvas_rolagem.configure(yscrollcommand=scrollbar.set)
        canvas_rolagem.bind("<Configure>", lambda e: canvas_rolagem.itemconfig(1, width=e.width))
        canvas_rolagem.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # ---- 1) evolução do total do PC ao longo do tempo ----
        totais = db.historico_total_build(build["id"])
        # Vários cliques em "Finalizar" seguidos sem o preço mudar geram
        # totais repetidos em sequência — isso só empilhava rótulos idênticos
        # um em cima do outro no gráfico. Junta esses pontos.
        pontos_total = []
        for t in totais:
            if pontos_total and abs(pontos_total[-1]["total"] - t["total"]) < 0.01:
                continue
            pontos_total.append(t)

        if len(pontos_total) >= 2:
            tk.Label(
                conteudo, text="Evolução do total salvo", font=("Segoe UI", 10, "bold"),
                bg=COR_FUNDO, fg=COR_TEXTO,
            ).pack(anchor="w", padx=14, pady=(12, 0))

            datas = [_dt.strptime(t["calculado_em"], "%Y-%m-%d %H:%M:%S") for t in pontos_total]
            valores = [t["total"] for t in pontos_total]

            fig1 = Figure(figsize=(7, 2.6), dpi=100)
            fig1.patch.set_facecolor(COR_FUNDO)
            ax1 = fig1.add_subplot(111)
            ax1.set_facecolor(COR_CARD_BG)
            ax1.plot(datas, valores, marker="o", color=COR_ACCENT, linewidth=2)
            for i, (x, y) in enumerate(zip(datas, valores)):
                acima = i % 2 == 0
                ax1.annotate(
                    formatar_preco(y), (x, y), textcoords="offset points",
                    xytext=(0, 10 if acima else -14),
                    fontsize=8, ha="center", va="bottom" if acima else "top", color=COR_TEXTO,
                )
            ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
            fig1.autofmt_xdate(rotation=25)
            ax1.grid(True, alpha=0.25, color=COR_TEXTO_MUTED)
            ax1.margins(x=0.15, y=0.45)
            _estilizar_eixo(ax1)
            fig1.tight_layout()

            canvas1 = FigureCanvasTkAgg(fig1, master=conteudo)
            canvas1.draw()
            canvas1.get_tk_widget().pack(fill="x", padx=10, pady=(4, 4))

        # ---- 2) qual peça ficou mais cara/barata desde a última checagem ----
        itens = db.listar_itens_build(build["id"])
        dados = []
        for categoria_chave in ORDEM_CATEGORIAS:
            item = itens.get(categoria_chave)
            if not item or not item.get("produto_id"):
                continue
            variacao = db.variacao_preco(item["produto_id"])
            if not variacao or variacao.get("anterior_min") is None:
                continue
            dados.append({
                "rotulo": f"{CATEGORIAS[categoria_chave]} — {(item.get('titulo') or '')[:28]}",
                "diferenca": variacao["diferenca"],
                "status": variacao["status"],
            })

        tk.Label(
            conteudo, text="Variação de preço por peça (desde a busca anterior)",
            font=("Segoe UI", 10, "bold"), bg=COR_FUNDO, fg=COR_TEXTO,
        ).pack(anchor="w", padx=14, pady=(14, 0))

        if not dados:
            tk.Label(
                conteudo, bg=COR_FUNDO, fg=COR_TEXTO_FRACO, wraplength=700, justify="left",
                text="Ainda não há duas checagens de preço pra comparar peça por peça. Use "
                     "“🔄 Recalcular preços de todas as peças” de novo daqui a um tempo "
                     "pra esse gráfico aparecer.",
            ).pack(anchor="w", padx=14, pady=8)
            return

        dados.sort(key=lambda d: d["diferenca"])

        mais_barata = dados[0] if dados[0]["diferenca"] < -0.01 else None
        mais_cara = dados[-1] if dados[-1]["diferenca"] > 0.01 else None
        resumo = []
        if mais_barata:
            resumo.append(f"🔻 Mais barata: {mais_barata['rotulo']} ({formatar_preco(mais_barata['diferenca'])})")
        if mais_cara:
            resumo.append(f"🔺 Mais cara: {mais_cara['rotulo']} (+{formatar_preco(mais_cara['diferenca'])})")
        tk.Label(
            conteudo,
            text="   ·   ".join(resumo) if resumo else "Nenhuma peça mudou de preço desde a última checagem.",
            bg=COR_FUNDO, fg=COR_TEXTO_MUTED, wraplength=740, justify="left", font=("Segoe UI", 9),
        ).pack(anchor="w", padx=14, pady=(2, 6))

        cores = {"verde": COR_VERDE, "vermelho": COR_VERMELHO, "neutro": COR_NEUTRO}
        maior_abs = max((abs(d["diferenca"]) for d in dados), default=0) or 1
        altura = max(2.2, 0.55 * len(dados) + 0.8)
        fig2 = Figure(figsize=(7, altura), dpi=100)
        fig2.patch.set_facecolor(COR_FUNDO)
        ax2 = fig2.add_subplot(111)
        ax2.set_facecolor(COR_CARD_BG)

        y_pos = list(range(len(dados)))
        ax2.barh(y_pos, [d["diferenca"] for d in dados], color=[cores[d["status"]] for d in dados], height=0.6)
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels([d["rotulo"] for d in dados], fontsize=8, color=COR_TEXTO)
        ax2.axvline(0, color=COR_TEXTO_MUTED, linewidth=1)
        # Espaço simétrico dos dois lados do zero — sem isso, o rótulo da
        # maior barra ficava colado (às vezes cortado) na borda da figura.
        ax2.set_xlim(-maior_abs * 1.4, maior_abs * 1.4)
        ax2.grid(True, axis="x", alpha=0.25, color=COR_TEXTO_MUTED)
        _estilizar_eixo(ax2)

        for i, d in enumerate(dados):
            diff = d["diferenca"]
            if abs(diff) < 0.01:
                texto, cor_texto = "sem mudança", COR_TEXTO_FRACO
            else:
                texto = f"{'+' if diff > 0 else ''}{formatar_preco(diff)}"
                cor_texto = COR_TEXTO
            ax2.annotate(
                texto, (diff, i), xytext=(8 if diff >= 0 else -8, 0), textcoords="offset points",
                va="center", ha="left" if diff >= 0 else "right", fontsize=8, color=cor_texto,
            )
        fig2.tight_layout()

        canvas2 = FigureCanvasTkAgg(fig2, master=conteudo)
        canvas2.draw()
        canvas2.get_tk_widget().pack(fill="x", padx=10, pady=(4, 14))

    def _slot_build(self, container, build, categoria_chave, item_atual):
        rotulo = CATEGORIAS[categoria_chave]
        card = tk.Frame(container, bg=COR_CARD_BG, highlightbackground=COR_CARD_BORDA, highlightthickness=1)
        card.pack(fill="x", pady=5, padx=2)

        esquerda = tk.Frame(card, bg=COR_CARD_BG)
        esquerda.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        tk.Label(esquerda, text=rotulo, font=("Segoe UI", 11, "bold"), bg=COR_CARD_BG, fg=COR_TEXTO).pack(anchor="w")

        if item_atual and item_atual.get("preco"):
            texto_selecionavel(
                esquerda,
                f"{item_atual['titulo']}  —  {formatar_preco(item_atual['preco'])} na {item_atual['loja']}",
                font=("Segoe UI", 10), fg=COR_TEXTO_MUTED, largura_chars=55,
            ).pack(anchor="w", pady=(2, 0))
        else:
            tk.Label(esquerda, text="Nenhuma peça selecionada.", bg=COR_CARD_BG, fg=COR_TEXTO_FRACO).pack(anchor="w")

        direita = tk.Frame(card, bg=COR_CARD_BG)
        direita.pack(side="right", padx=14, pady=10)

        criar_botao(
            direita, "Selecionar peça",
            lambda: self._selecionar_peca_para_slot(build, categoria_chave), estilo="primario"
        ).pack(side="left", padx=4)

        if item_atual:
            criar_botao(
                direita, "Remover",
                lambda: self._remover_peca_slot(build, categoria_chave), estilo="secundario"
            ).pack(side="left", padx=4)

    def _remover_peca_slot(self, build, categoria_chave):
        db.remover_item_build(build["id"], categoria_chave)
        self.mostrar_montagem()

    def _selecionar_peca_para_slot(self, build, categoria_chave):
        produtos = db.listar_produtos(categoria_chave)
        if not produtos:
            if messagebox.askyesno(
                "Nenhum item cadastrado",
                f"Você ainda não tem nenhum item em {CATEGORIAS[categoria_chave]}.\n"
                f"Quer buscar um agora?"
            ):
                self.mostrar_busca()
            return

        janela = tk.Toplevel(self, bg=COR_FUNDO)
        janela.title(f"Selecionar — {CATEGORIAS[categoria_chave]}")
        janela.geometry("420x380")

        tk.Label(
            janela, text="Escolha um item da sua lista:", font=("Segoe UI", 10, "bold"),
            bg=COR_FUNDO, fg=COR_TEXTO,
        ).pack(anchor="w", padx=12, pady=(12, 4))

        listbox = tk.Listbox(
            janela, font=("Segoe UI", 10), bg=COR_CARD_BG, fg=COR_TEXTO,
            selectbackground=COR_ACCENT, selectforeground="#1a1108",
            relief="flat", highlightthickness=1, highlightbackground=COR_CARD_BORDA,
        )
        listbox.pack(fill="both", expand=True, padx=12, pady=6)
        for p in produtos:
            listbox.insert("end", p["nome"])

        status_var = tk.StringVar(value="")
        tk.Label(janela, textvariable=status_var, bg=COR_FUNDO, fg=COR_TEXTO_MUTED).pack(padx=12, anchor="w")

        def confirmar():
            sel = listbox.curselection()
            if not sel:
                return
            produto = produtos[sel[0]]
            status_var.set("Buscando preço mais atual...")
            janela.update_idletasks()

            def trabalho():
                if produto.get("modo") == "url" and produto.get("url_fixa"):
                    resultados = buscar_produto_por_url(produto["url_fixa"])
                else:
                    resultados = buscar_em_todas_as_lojas(produto["termo_busca"], lojas=LOJAS_DISPONIVEIS)
                if resultados:
                    db.registrar_precos(produto["id"], resultados)
                    melhor = min(resultados, key=lambda r: r["preco"])
                else:
                    melhor = db.melhor_preco_atual(produto["id"])

                def finalizar():
                    if melhor:
                        db.definir_item_build(
                            build["id"], categoria_chave, produto["id"],
                            melhor.get("loja"), melhor.get("titulo") or produto["nome"],
                            melhor["preco"], melhor.get("url", "")
                        )
                    janela.destroy()
                    if self._tela_ativa == "montagem":
                        self.mostrar_montagem()

                self.fila_eventos.put(finalizar)

            threading.Thread(target=trabalho, daemon=True).start()

        criar_botao(janela, "Usar este item", confirmar, estilo="primario").pack(
            pady=10
        )

    # ==================================================================
    # TELA: Rotinas (checagem automática e agendada de um PC)
    # ==================================================================
    def mostrar_rotinas(self):
        self._limpar_conteudo()
        self._tela_ativa = "rotinas"
        frame = self.area_conteudo

        topo = tk.Frame(frame, bg=COR_FUNDO)
        topo.pack(fill="x", padx=20, pady=(18, 6))
        tk.Label(topo, text="Rotinas", font=(FONTE_TITULO, 22, "bold"), bg=COR_FUNDO, fg=COR_TEXTO).pack(side="left")
        criar_botao(topo, "➕ Nova rotina", self._rotina_dialog, estilo="primario").pack(side="right")

        if tarefa_agendada_existe():
            status_texto = "✅ Tarefa agendada do Windows ativa — as rotinas rodam mesmo com o app fechado."
            cor_status = COR_VERDE
        else:
            status_texto = (
                "⚠️ A tarefa agendada do Windows ainda não foi criada — crie uma rotina pra registrá-la. "
                "Enquanto isso, as rotinas só rodam com o app aberto."
            )
            cor_status = COR_TEXTO_FRACO
        tk.Label(
            frame, text=status_texto, font=("Segoe UI", 9), bg=COR_FUNDO, fg=cor_status,
            wraplength=900, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 12))

        rotinas = db.listar_rotinas()
        if not rotinas:
            tk.Label(
                frame, text="Nenhuma rotina cadastrada. Crie uma pra checar o preço de um PC automaticamente.",
                bg=COR_FUNDO, fg=COR_TEXTO_MUTED, font=("Segoe UI", 11)
            ).pack(padx=20, pady=30, anchor="w")
            return

        cont = tk.Frame(frame, bg=COR_FUNDO)
        cont.pack(fill="both", expand=True, padx=20, pady=6)

        canvas = tk.Canvas(cont, bg=COR_FUNDO, highlightthickness=0)
        scrollbar = ttk.Scrollbar(cont, orient="vertical", command=canvas.yview)
        lista_frame = tk.Frame(canvas, bg=COR_FUNDO)
        lista_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=lista_frame, anchor="nw", width=1)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(1, width=e.width))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for rotina in rotinas:
            self._linha_rotina(lista_frame, rotina)

    def _linha_rotina(self, container, rotina):
        card = tk.Frame(container, bg=COR_CARD_BG, highlightbackground=COR_CARD_BORDA, highlightthickness=1)
        card.pack(fill="x", pady=5, padx=2)

        esquerda = tk.Frame(card, bg=COR_CARD_BG)
        esquerda.pack(side="left", fill="both", expand=True, padx=14, pady=10)

        nome_alvo = rotinas_mod.descricao_alvo(rotina)
        tk.Label(esquerda, text=nome_alvo, font=("Segoe UI", 11, "bold"), bg=COR_CARD_BG, fg=COR_TEXTO).pack(anchor="w")

        recorrencia = rotinas_mod.descricao_recorrencia(rotina)
        horarios = rotinas_mod.descricao_horarios(rotina)
        texto_status = "" if rotina.get("ativa") else "  ·  inativa"
        tk.Label(
            esquerda, text=f"⏰ {horarios}  ·  {recorrencia}{texto_status}", font=(FONTE_MONO, 10),
            bg=COR_CARD_BG, fg=COR_TEXTO_MUTED if rotina.get("ativa") else COR_TEXTO_FRACO,
        ).pack(anchor="w", pady=(2, 0))

        ultima = rotina.get("ultima_execucao")
        texto_ultima = f"Última checagem: {ultima}" if ultima else "Ainda não rodou."
        tk.Label(
            esquerda, text=texto_ultima, font=("Segoe UI", 9), bg=COR_CARD_BG, fg=COR_TEXTO_FRACO,
        ).pack(anchor="w", pady=(2, 0))

        if rotina.get("alerta_email"):
            condicoes = []
            if rotina.get("alerta_total_abaixo"):
                condicoes.append(f"total < {formatar_preco(rotina['alerta_total_abaixo'])}")
            if rotina.get("alertar_menor_preco"):
                condicoes.append("novo menor preço de alguma peça")
            texto_alerta = f"📧 avisa {rotina['alerta_email']} se " + " ou ".join(condicoes) if condicoes else \
                f"📧 avisa {rotina['alerta_email']}"
            tk.Label(
                esquerda, text=texto_alerta, font=("Segoe UI", 9), bg=COR_CARD_BG, fg=COR_TEXTO_FRACO,
                wraplength=420, justify="left",
            ).pack(anchor="w", pady=(2, 0))

        direita = tk.Frame(card, bg=COR_CARD_BG)
        direita.pack(side="right", padx=14, pady=10)

        criar_botao(
            direita, "▶ Rodar agora", lambda: self._rodar_rotina_agora(rotina), estilo="primario"
        ).pack(side="left", padx=4)
        criar_botao(
            direita, "✏️ Editar", lambda: self._rotina_dialog(rotina), estilo="secundario"
        ).pack(side="left", padx=4)
        criar_botao(
            direita, "Desativar" if rotina.get("ativa") else "Ativar",
            lambda: self._alternar_rotina(rotina), estilo="secundario"
        ).pack(side="left", padx=4)
        criar_botao(
            direita, "🗑️", lambda: self._remover_rotina(rotina), estilo="perigo"
        ).pack(side="left", padx=4)

    def _alternar_rotina(self, rotina):
        db.definir_rotina_ativa(rotina["id"], not rotina.get("ativa"))
        self.mostrar_rotinas()

    def _remover_rotina(self, rotina):
        nome_alvo = rotinas_mod.descricao_alvo(rotina)
        if not messagebox.askyesno("Remover rotina", f"Remover a rotina de checagem de “{nome_alvo}”?"):
            return
        db.remover_rotina(rotina["id"])
        if not db.listar_rotinas():
            remover_tarefa_agendada()
        self.mostrar_rotinas()

    def _rodar_rotina_agora(self, rotina):
        if rotina.get("alvo_tipo", "build") == "build" and not db.obter_build(rotina["build_id"]):
            messagebox.showwarning("PC não encontrado", "O PC dessa rotina não existe mais.")
            return

        nome_alvo = rotinas_mod.descricao_alvo(rotina)
        janela = tk.Toplevel(self, bg=COR_FUNDO)
        janela.title("Rodando rotina...")
        janela.geometry("380x150")
        janela.resizable(False, False)
        tk.Label(
            janela, text=f"Checando preços de “{nome_alvo}”...", pady=10, wraplength=340,
            bg=COR_FUNDO, fg=COR_TEXTO,
        ).pack()
        status_var = tk.StringVar(value="Iniciando...")
        tk.Label(janela, textvariable=status_var, bg=COR_FUNDO, fg=COR_TEXTO_MUTED, wraplength=340).pack()
        barra = ttk.Progressbar(janela, mode="indeterminate")
        barra.pack(fill="x", padx=20, pady=10)
        barra.start(12)

        def progresso(nome_peca):
            self.fila_eventos.put(lambda: status_var.set(nome_peca))

        avisos_execucao = []

        def trabalho():
            rotinas_mod.executar_rotina(rotina, callback_progresso=progresso, log_fn=avisos_execucao.append)

            def finalizar():
                janela.destroy()
                if avisos_execucao:
                    messagebox.showinfo("Rotina concluída", "\n".join(avisos_execucao))
                if self._tela_ativa == "rotinas":
                    self.mostrar_rotinas()

            self.fila_eventos.put(finalizar)

        threading.Thread(target=trabalho, daemon=True).start()

    def _rotina_dialog(self, rotina=None):
        """Mesma janela serve pra criar (rotina=None) e pra editar (rotina=dict existente)."""
        builds = db.listar_builds()
        editando = rotina is not None

        janela = tk.Toplevel(self, bg=COR_FUNDO)
        janela.title("Editar rotina" if editando else "Nova rotina")
        janela.geometry("480x720")
        janela.resizable(False, True)

        rodape = tk.Frame(janela, bg=COR_FUNDO)
        rodape.pack(side="bottom", fill="x", pady=12)

        # Conteúdo com rolagem — a janela cresceu bastante com a escolha de
        # alvo e a lista de horários, sem rolagem ficava cortado em telas
        # menores.
        area = tk.Frame(janela, bg=COR_FUNDO)
        area.pack(side="top", fill="both", expand=True)
        canvas_rolagem = tk.Canvas(area, bg=COR_FUNDO, highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=canvas_rolagem.yview)
        conteudo = tk.Frame(canvas_rolagem, bg=COR_FUNDO)
        conteudo.bind("<Configure>", lambda e: canvas_rolagem.configure(scrollregion=canvas_rolagem.bbox("all")))
        canvas_rolagem.create_window((0, 0), window=conteudo, anchor="nw", width=1)
        canvas_rolagem.configure(yscrollcommand=scrollbar.set)
        canvas_rolagem.bind("<Configure>", lambda e: canvas_rolagem.itemconfig(1, width=e.width))
        canvas_rolagem.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _rolar(event):
            canvas_rolagem.yview_scroll(-1 * int(event.delta / 120), "units")

        canvas_rolagem.bind("<Enter>", lambda e: canvas_rolagem.bind_all("<MouseWheel>", _rolar))
        canvas_rolagem.bind("<Leave>", lambda e: canvas_rolagem.unbind_all("<MouseWheel>"))

        # --- O que verificar: um PC montado, uma categoria, ou tudo ---
        tk.Label(
            conteudo, text="O que verificar:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED, font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=16, pady=(16, 2))

        if editando:
            alvo_tipo_inicial = rotina.get("alvo_tipo") or "build"
        else:
            alvo_tipo_inicial = "build" if builds else "categoria"
        alvo_tipo_var = tk.StringVar(value=alvo_tipo_inicial)

        opcoes_alvo = {}
        for valor, rotulo in (
            ("build", "Um PC montado"), ("categoria", "Uma categoria específica"),
            ("tudo", "Tudo o que está cadastrado"),
        ):
            rb = tk.Radiobutton(
                conteudo, text=rotulo, value=valor, variable=alvo_tipo_var,
                bg=COR_FUNDO, fg=COR_TEXTO, selectcolor=COR_CARD_BG, activebackground=COR_FUNDO,
                activeforeground=COR_TEXTO, highlightthickness=0, anchor="w",
            )
            if valor == "build" and not builds:
                rb.config(state="disabled")
            rb.pack(anchor="w", padx=16)
            opcoes_alvo[valor] = rb

        frame_escolha_build = tk.Frame(conteudo, bg=COR_FUNDO)
        if builds:
            combo_build = ttk.Combobox(frame_escolha_build, values=[b["nome"] for b in builds], state="readonly", width=38)
            combo_build.pack(anchor="w")
            idx_build_atual = 0
            if editando and rotina.get("build_id"):
                idx_build_atual = next((i for i, b in enumerate(builds) if b["id"] == rotina["build_id"]), 0)
            combo_build.current(idx_build_atual)
        else:
            combo_build = None
            tk.Label(
                frame_escolha_build, text="Crie um PC em “Montar PC” antes de escolher essa opção.",
                bg=COR_FUNDO, fg=COR_TEXTO_FRACO, font=("Segoe UI", 9),
            ).pack(anchor="w")

        frame_escolha_categoria = tk.Frame(conteudo, bg=COR_FUNDO)
        combo_categoria_alvo = ttk.Combobox(
            frame_escolha_categoria, values=list(CATEGORIAS.values()), state="readonly", width=38
        )
        combo_categoria_alvo.pack(anchor="w")
        if editando and rotina.get("alvo_categoria") in CATEGORIAS:
            combo_categoria_alvo.set(CATEGORIAS[rotina["alvo_categoria"]])
        else:
            combo_categoria_alvo.current(0)

        frame_escolha_tudo = tk.Frame(conteudo, bg=COR_FUNDO)
        tk.Label(
            frame_escolha_tudo,
            text="Vai checar o preço de todos os produtos cadastrados, em qualquer categoria.",
            bg=COR_FUNDO, fg=COR_TEXTO_FRACO, font=("Segoe UI", 9), wraplength=400, justify="left",
        ).pack(anchor="w")

        def atualizar_visibilidade_alvo(*_a):
            frame_escolha_build.pack_forget()
            frame_escolha_categoria.pack_forget()
            frame_escolha_tudo.pack_forget()
            tipo = alvo_tipo_var.get()
            if tipo == "build":
                frame_escolha_build.pack(anchor="w", padx=16, pady=(4, 0))
            elif tipo == "categoria":
                frame_escolha_categoria.pack(anchor="w", padx=16, pady=(4, 0))
            else:
                frame_escolha_tudo.pack(anchor="w", padx=16, pady=(4, 0))
            atualizar_visibilidade_alerta_total()

        for rb in opcoes_alvo.values():
            rb.config(command=atualizar_visibilidade_alvo)

        tk.Frame(conteudo, bg=COR_CARD_BORDA, height=1).pack(fill="x", padx=16, pady=(16, 10))

        # --- Horário(s) da checagem (pode ter mais de um por dia) ---
        tk.Label(
            conteudo, text="Horário(s) da checagem:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED, font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=16)

        horarios_lista = (
            sorted({h.strip() for h in (rotina.get("horarios") or "").split(",") if h.strip()})
            if editando else ["09:00"]
        )

        frame_horarios_lista = tk.Frame(conteudo, bg=COR_FUNDO)
        frame_horarios_lista.pack(anchor="w", padx=16, pady=(6, 0), fill="x")

        def redesenhar_horarios():
            for w in frame_horarios_lista.winfo_children():
                w.destroy()
            if not horarios_lista:
                tk.Label(
                    frame_horarios_lista, text="Nenhum horário adicionado ainda.",
                    bg=COR_FUNDO, fg=COR_TEXTO_FRACO, font=("Segoe UI", 9),
                ).pack(anchor="w")
                return
            for h in sorted(horarios_lista):
                linha = tk.Frame(frame_horarios_lista, bg=COR_CARD_BG)
                linha.pack(anchor="w", pady=2, fill="x")
                tk.Label(
                    linha, text=f"⏰ {h}", font=(FONTE_MONO, 10), bg=COR_CARD_BG, fg=COR_TEXTO,
                ).pack(side="left", padx=(10, 4), pady=5)
                tk.Button(
                    linha, text="✕", command=lambda hh=h: remover_horario(hh),
                    bg=COR_CARD_BG, fg=COR_VERMELHO, bd=0, activebackground=COR_CARD_BG,
                    activeforeground=COR_VERMELHO, cursor="hand2", font=("Segoe UI", 9, "bold"),
                ).pack(side="right", padx=10)

        def remover_horario(h):
            if h in horarios_lista:
                horarios_lista.remove(h)
            redesenhar_horarios()

        redesenhar_horarios()

        tk.Label(conteudo, text="Adicionar horário:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED).pack(
            anchor="w", padx=16, pady=(10, 0)
        )
        linha_add_horario = tk.Frame(conteudo, bg=COR_FUNDO)
        linha_add_horario.pack(anchor="w", padx=16, pady=4)
        combo_hora = ttk.Combobox(linha_add_horario, values=[f"{h:02d}" for h in range(24)], state="readonly", width=4)
        combo_minuto = ttk.Combobox(linha_add_horario, values=[f"{m:02d}" for m in range(0, 60, 5)], state="readonly", width=4)
        combo_hora.set("09")
        combo_hora.pack(side="left")
        tk.Label(linha_add_horario, text=":", bg=COR_FUNDO, fg=COR_TEXTO).pack(side="left", padx=3)
        combo_minuto.set("00")
        combo_minuto.pack(side="left")

        def adicionar_horario():
            novo = f"{combo_hora.get()}:{combo_minuto.get()}"
            if novo not in horarios_lista:
                horarios_lista.append(novo)
                redesenhar_horarios()

        criar_botao(
            linha_add_horario, "➕ Adicionar", adicionar_horario, estilo="secundario", font_size=9
        ).pack(side="left", padx=(10, 0))

        tk.Frame(conteudo, bg=COR_CARD_BORDA, height=1).pack(fill="x", padx=16, pady=(16, 10))

        tk.Label(conteudo, text="Repetir:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED).pack(anchor="w", padx=16, pady=(0, 0))
        if editando:
            if not rotina.get("repetir"):
                tipo_inicial = "unica"
            elif rotina.get("dias_semana"):
                tipo_inicial = "dias"
            else:
                tipo_inicial = "diaria"
        else:
            tipo_inicial = "diaria"
        tipo_var = tk.StringVar(value=tipo_inicial)

        opcoes_radio = {}
        for valor, rotulo in (
            ("diaria", "Todo dia"), ("dias", "Dias específicos da semana"), ("unica", "Uma vez só"),
        ):
            rb = tk.Radiobutton(
                conteudo, text=rotulo, value=valor, variable=tipo_var,
                bg=COR_FUNDO, fg=COR_TEXTO, selectcolor=COR_CARD_BG, activebackground=COR_FUNDO,
                activeforeground=COR_TEXTO, highlightthickness=0, anchor="w",
            )
            rb.pack(anchor="w", padx=16)
            opcoes_radio[valor] = rb

        frame_dias = tk.Frame(conteudo, bg=COR_FUNDO)
        dias_marcados = set((rotina.get("dias_semana") or "").split(",")) if editando else set()
        dias_vars = {d: tk.BooleanVar(value=d in dias_marcados) for d in rotinas_mod.DIAS_SEMANA}
        for d in rotinas_mod.DIAS_SEMANA:
            tk.Checkbutton(
                frame_dias, text=rotinas_mod.NOMES_DIAS[d], variable=dias_vars[d],
                bg=COR_FUNDO, fg=COR_TEXTO, selectcolor=COR_CARD_BG, activebackground=COR_FUNDO,
                activeforeground=COR_TEXTO, highlightthickness=0,
            ).pack(side="left", padx=2)

        frame_data = tk.Frame(conteudo, bg=COR_FUNDO)
        tk.Label(frame_data, text="Data (DD/MM/AAAA):", bg=COR_FUNDO, fg=COR_TEXTO_MUTED).pack(side="left")
        entry_data = criar_entry(frame_data, width=12)
        if editando and rotina.get("data_unica"):
            try:
                data_texto = datetime.strptime(rotina["data_unica"], "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                data_texto = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
        else:
            data_texto = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
        entry_data.insert(0, data_texto)
        entry_data.pack(side="left", padx=(6, 0), ipady=3)

        def atualizar_visibilidade(*_a):
            frame_dias.pack_forget()
            frame_data.pack_forget()
            if tipo_var.get() == "dias":
                frame_dias.pack(anchor="w", padx=16, pady=(6, 0))
            elif tipo_var.get() == "unica":
                frame_data.pack(anchor="w", padx=16, pady=(6, 0))

        for rb in opcoes_radio.values():
            rb.config(command=atualizar_visibilidade)
        atualizar_visibilidade()

        tk.Frame(conteudo, bg=COR_CARD_BORDA, height=1).pack(fill="x", padx=16, pady=(16, 10))

        alerta_var = tk.BooleanVar(value=bool(rotina.get("alerta_email")) if editando else True)
        frame_alerta = tk.Frame(conteudo, bg=COR_FUNDO)

        def alternar_frame_alerta():
            if alerta_var.get():
                frame_alerta.pack(anchor="w", padx=16, pady=(6, 0), fill="x")
            else:
                frame_alerta.pack_forget()
            atualizar_visibilidade_alerta_total()

        tk.Checkbutton(
            conteudo, text="📧  Avisar por e-mail quando o preço cair", variable=alerta_var,
            command=alternar_frame_alerta,
            bg=COR_FUNDO, fg=COR_TEXTO, selectcolor=COR_CARD_BG, activebackground=COR_FUNDO,
            activeforeground=COR_TEXTO, highlightthickness=0, anchor="w", font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=16)

        tk.Label(frame_alerta, text="E-mail para avisar:", bg=COR_FUNDO, fg=COR_TEXTO_MUTED).pack(anchor="w")
        entry_email = criar_entry(frame_alerta, width=32)
        email_inicial = (rotina.get("alerta_email") if editando else None) or "pablo@zandonadi.adv.br"
        entry_email.insert(0, email_inicial)
        entry_email.pack(anchor="w", pady=(2, 8), ipady=3)

        total_inicial = bool(rotina.get("alerta_total_abaixo")) if editando else True
        total_var = tk.BooleanVar(value=total_inicial)
        linha_total_alerta = tk.Frame(frame_alerta, bg=COR_FUNDO)
        tk.Checkbutton(
            linha_total_alerta, text="Total do PC ficar abaixo de: R$", variable=total_var,
            bg=COR_FUNDO, fg=COR_TEXTO, selectcolor=COR_CARD_BG, activebackground=COR_FUNDO,
            activeforeground=COR_TEXTO, highlightthickness=0,
        ).pack(side="left")
        entry_limite = criar_entry(linha_total_alerta, width=10)
        if editando and rotina.get("alerta_total_abaixo"):
            entry_limite.insert(0, f"{rotina['alerta_total_abaixo']:.2f}")
        entry_limite.pack(side="left", padx=(4, 0), ipady=2)

        menor_preco_var = tk.BooleanVar(
            value=bool(rotina.get("alertar_menor_preco")) if editando else True
        )
        checkbox_menor_preco = tk.Checkbutton(
            frame_alerta, text="Algum item bater um novo menor preço histórico", variable=menor_preco_var,
            bg=COR_FUNDO, fg=COR_TEXTO, selectcolor=COR_CARD_BG, activebackground=COR_FUNDO,
            activeforeground=COR_TEXTO, highlightthickness=0,
        )
        checkbox_menor_preco.pack(anchor="w", pady=(4, 0))

        def atualizar_visibilidade_alerta_total():
            # "Total do PC" só faz sentido quando o alvo é um PC inteiro —
            # categoria/tudo não têm um "total" único.
            linha_total_alerta.pack_forget()
            if alvo_tipo_var.get() == "build" and alerta_var.get():
                linha_total_alerta.pack(anchor="w", fill="x", before=checkbox_menor_preco)

        if alerta_var.get():
            frame_alerta.pack(anchor="w", padx=16, pady=(6, 0), fill="x")

        # Só agora que todos os frames referenciados (alvo + alerta) existem
        # é seguro chamar isso pela primeira vez.
        atualizar_visibilidade_alvo()

        def salvar():
            alvo_tipo = alvo_tipo_var.get()
            build_id = None
            alvo_categoria = None

            if alvo_tipo == "build":
                if combo_build is None or combo_build.current() < 0:
                    messagebox.showwarning("Atenção", "Escolha um PC (ou crie um em “Montar PC” antes).")
                    return
                build_id = builds[combo_build.current()]["id"]
            elif alvo_tipo == "categoria":
                rotulo_categoria = combo_categoria_alvo.get()
                encontrados = [k for k, v in CATEGORIAS.items() if v == rotulo_categoria]
                if not encontrados:
                    messagebox.showwarning("Atenção", "Escolha uma categoria.")
                    return
                alvo_categoria = encontrados[0]

            if not horarios_lista:
                messagebox.showwarning("Atenção", "Adicione pelo menos um horário.")
                return
            horarios_final = ",".join(sorted(horarios_lista))

            tipo = tipo_var.get()

            alerta_email = None
            alerta_total_abaixo = None
            alertar_menor_preco = False
            if alerta_var.get():
                alerta_email = entry_email.get().strip()
                if not alerta_email or "@" not in alerta_email:
                    messagebox.showwarning("E-mail inválido", "Digite um e-mail válido pra receber o alerta.")
                    return
                if alvo_tipo == "build" and total_var.get():
                    texto_limite = entry_limite.get().strip().replace(",", ".")
                    try:
                        alerta_total_abaixo = float(texto_limite)
                    except ValueError:
                        messagebox.showwarning(
                            "Valor inválido", "Digite um valor numérico pro limite do total (ex.: 4500)."
                        )
                        return
                alertar_menor_preco = menor_preco_var.get()

            if tipo == "unica":
                texto_data = entry_data.get().strip()
                try:
                    data_obj = datetime.strptime(texto_data, "%d/%m/%Y")
                except ValueError:
                    messagebox.showwarning("Data inválida", "Use o formato DD/MM/AAAA.")
                    return
                repetir_final, dias_final, data_final = False, None, data_obj.strftime("%Y-%m-%d")
            else:
                dias_selecionados = [d for d, v in dias_vars.items() if v.get()] if tipo == "dias" else []
                if tipo == "dias" and not dias_selecionados:
                    messagebox.showwarning("Atenção", "Escolha pelo menos um dia da semana.")
                    return
                repetir_final, dias_final, data_final = True, ",".join(dias_selecionados) or None, None

            if editando:
                db.atualizar_rotina(
                    rotina["id"], alvo_tipo, horarios_final, repetir=repetir_final,
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
                    "Não consegui criar a tarefa agendada do Windows agora. Ela ainda roda sozinha "
                    "enquanto o app estiver aberto — pra rodar também com o app fechado, tente de novo "
                    "mais tarde ou peça ajuda."
                )
            if alerta_email and not notificacoes.remetente_configurado():
                avisos.append(
                    "O alerta por e-mail está ativado, mas o remetente ainda não foi configurado. "
                    "Abra o arquivo email_config.py e preencha SMTP_EMAIL e SMTP_SENHA_APP (veja as "
                    "instruções no topo do arquivo) — sem isso, o e-mail não sai."
                )
            if avisos:
                titulo_aviso = "Rotina atualizada!" if editando else "Rotina criada!"
                messagebox.showwarning("Rotina salva", f"{titulo_aviso}\n\n" + "\n\n".join(avisos))
            janela.destroy()
            self.mostrar_rotinas()

        criar_botao(rodape, "Salvar alterações" if editando else "Criar rotina", salvar, estilo="primario").pack()


def main():
    if "--rotina-checador" in sys.argv:
        # Chamado pela Tarefa Agendada do Windows quando o app está
        # "congelado" (instalado via o instalador) — roda só a checagem de
        # rotinas, sem abrir nenhuma janela, e sai. Ver _comando_tarefa_agendada().
        import rotina_checador
        rotina_checador.main()
        return
    db.inicializar_banco()
    app = RastreadorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
