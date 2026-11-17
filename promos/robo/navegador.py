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
                print(f"[navegador] nao abriu o {canal or 'navegador do Playwright'}: {str(e).splitlines()[0][:200]}")
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

    def esperar(self, seletor, ms=8000):
        """Espera o seletor aparecer. Devolve False se nao apareceu no tempo."""
        try:
            self.pagina.wait_for_selector(seletor, timeout=ms, state="attached")
            return True
        except Exception:
            return False

    def foto(self, caminho):
        try:
            self.pagina.screenshot(path=str(caminho), full_page=False)
        except Exception:
            pass

    def avaliar(self, js):
        return self.pagina.evaluate(js)

    def avaliar_com(self, js, arg):
        return self.pagina.evaluate(js, arg)

    def rolar(self, vezes=3):
        """Desce a pagina aos poucos para carregar fotos e cartoes que so aparecem com a rolagem."""
        for _ in range(vezes):
            try:
                self.pagina.mouse.wheel(0, 2500)
                self.pagina.wait_for_timeout(600)
            except Exception:
                return

    def fechar(self):
        for alvo, metodo in ((self.ctx, "close"), (self._pw, "stop")):
            try:
                if alvo:
                    getattr(alvo, metodo)()
            except Exception:
                pass
        self._pw = self.ctx = self.pagina = None
