"""Mercado Livre pelo site (sem API): o robo abre a busca num navegador ja logado e le os precos.

O site so mostra a busca para quem esta logado. Por isso e preciso entrar na conta UMA vez no
navegador do robo:  rodar.bat entrar mercadolivre   (o login fica guardado no perfil do robo).
- Se o site voltar a pedir login ou verificacao, a coleta para e avisa. O robo nao contorna isso.
- So passa na reputacao o anuncio marcado como loja oficial na propria listagem.
- O link de afiliado nao e gerado aqui: continua saindo do portal de afiliados.
"""
import random
import re
import time
import urllib.parse

from .base import ErroDaFonte, Item

BASE = "https://lista.mercadolivre.com.br"
ENTRADA = "https://www.mercadolivre.com.br/"

JS_BUSCA = r"""() => {
  const num = (raiz) => { if (!raiz) return 0;
    const f = raiz.querySelector('.andes-money-amount__fraction'), c = raiz.querySelector('.andes-money-amount__cents');
    if (!f) return 0;
    return parseInt(f.textContent.replace(/\D/g, '') || '0', 10) * 100 + (c ? parseInt(c.textContent.replace(/\D/g, '') || '0', 10) : 0); };
  const parcelas = (t) => { const m = (t || '').replace(/\s+/g, ' ').match(/(\d{1,2})\s*x\s*(?:de\s*)?R\$\s*([\d.]+,\d{2})(.{0,30})/i);
    return m ? m[1] + 'x de R$ ' + m[2] + (/sem juros/i.test(m[3]) ? ' sem juros' : '') : ''; };
  const cards = [...document.querySelectorAll('li.ui-search-layout__item')];
  const login = /account-verification|\/login|\/registration/.test(location.href);
  return {
    url: location.href, login: login,
    amostra_html: cards.slice(0, 2).map(c => c.outerHTML.replace(/\s+/g, ' ').slice(0, 6000)),
    itens: cards.map(c => {
      const a = c.querySelector('a.poly-component__title, .poly-component__title a, a.ui-search-link');
      const vend = c.querySelector('.poly-component__seller');
      const img = c.querySelector('img.poly-component__picture, img');
      const nota = c.querySelector('.poly-reviews__rating');
      const total = c.querySelector('.poly-reviews__total');
      return {
        titulo: a ? a.textContent.trim() : '', url: a ? a.href : '',
        preco: num(c.querySelector('.poly-price__current')),
        de: num(c.querySelector('s.andes-money-amount--previous, .andes-money-amount--previous')),
        vendedor: vend ? vend.textContent.replace(/\s+/g, ' ').trim() : '',
        oficial: !!c.querySelector('[aria-label*="oficial" i], [title*="oficial" i]') || /loja oficial/i.test(c.textContent),
        parcelas: parcelas((c.querySelector('.poly-price__installments') || {}).textContent),
        imagem: img ? (img.getAttribute('data-src') || img.src || '') : '',
        nota: nota ? parseFloat(nota.textContent.replace(',', '.')) || 0 : 0,
        avaliacoes: total ? parseInt(total.textContent.replace(/\D/g, '') || '0', 10) : 0
      };
    })
  };
}"""

ID_NA_URL = re.compile(r"(MLB-?\d+)")


def converter(no):
    """Um card da busca -> Item. None se faltar titulo, preco ou identificador."""
    url = (no.get("url") or "").split("#")[0].split("?")[0]
    m = ID_NA_URL.search(url)
    if not (m and no.get("titulo") and no.get("preco")):
        return None
    de = no.get("de") or 0
    vendedor = re.sub(r"^Por\s+", "", no.get("vendedor") or "").strip()
    return Item(loja="mercadolivre", id_loja=m.group(1).replace("-", ""), titulo=no["titulo"],
                preco_cent=no["preco"], original_cent=de if de > no["preco"] else 0,
                url=url, url_afiliado="", imagem=no.get("imagem") or "",
                vendedor=vendedor, selo="oficial" if no.get("oficial") else "",
                nota=float(no.get("nota") or 0), vendas=int(no.get("avaliacoes") or 0),
                parcelas=no.get("parcelas") or "")


class MercadoLivreSite:
    nome = "mercadolivre"

    def __init__(self, env, navegador, base=BASE, pausa=(4, 9)):
        self.nav, self.base, self.pausa = navegador, base, pausa
        self.bloqueada = False

    def url_busca(self, palavra, pagina=1):
        return f"{self.base}/" + urllib.parse.quote(palavra.strip().replace(" ", "-"))

    def buscar_bruto(self, palavra, pagina=1, por_pagina=0):
        if self.bloqueada:
            raise ErroDaFonte("Mercado Livre pediu login neste ciclo; coleta interrompida")
        self.nav.ir(self.url_busca(palavra, pagina))
        dados = self.nav.avaliar(JS_BUSCA)
        if dados.get("login"):
            self.bloqueada = True
            raise ErroDaFonte("Mercado Livre pediu login. Rode: rodar.bat entrar mercadolivre")
        return dados

    def buscar(self, palavra, paginas=1, por_pagina=0, pausa=0):
        nos = self.buscar_bruto(palavra)["itens"]
        if self.pausa:
            time.sleep(random.uniform(*self.pausa))
        return [i for i in (converter(no) for no in nos) if i]

    def fechar(self):
        self.nav.fechar()
