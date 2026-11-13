"""Navegador controlado pelo robo (Playwright), para lojas sem API utilizavel.

Usa o Edge (ou o Chrome) ja instalado no Windows, com um perfil proprio guardado em
dados/perfil_navegador. Assim um login feito uma vez (rodar.bat entrar ...) continua valendo.
Se a loja pedir CAPTCHA ou outra verificacao, o robo para e avisa; ele nao tenta resolver.
"""
from .fontes.base import ErroDaFonte, SemCredenciais

CANAIS = ("msedge", "chrome", None)     # None = navegador que vem com o Playwright


class Navegador:
    def __init__(self, perfil, visivel=False, canais=CANAIS):
        self.perfil, self.visivel, self.canais = perfil, visivel, canais
        self._pw = self.ctx = self.pagina = None

    def abrir_navegador(self):
        if self.pagina:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise SemCredenciais("falta instalar o Playwright: rode instalar.bat (uma vez so)")
        self._pw = sync_playwright().start()
        erro = None
        for canal in self.canais:
            try:
                self.ctx = self._pw.chromium.launch_persistent_context(
                    str(self.perfil), channel=canal, headless=not self.visivel,
                    locale="pt-BR", viewport={"width": 1366, "height": 900})
                break
            except Exception as e:          # canal nao instalado: tenta o proximo
                erro = e
        if not self.ctx:
            self.fechar()
            raise ErroDaFonte(f"nao foi possivel abrir o navegador: {str(erro)[:200]}")
        self.pagina = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def ir(self, url):
        self.abrir_navegador()
        try:
            self.pagina.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            raise ErroDaFonte(f"pagina nao carregou: {str(e)[:120]}")
        return self.pagina.url

    def avaliar(self, js):
        return self.pagina.evaluate(js)

    def fechar(self):
        for alvo, metodo in ((self.ctx, "close"), (self._pw, "stop")):
            try:
                if alvo:
                    getattr(alvo, metodo)()
            except Exception:
                pass
        self._pw = self.ctx = self.pagina = None
