"""Amazon pelo site (sem API): o robo abre a busca da amazon.com.br num navegador e le os precos.

Usado enquanto a conta de Associados nao e elegivel para a Creators API.
- A busca nao mostra o vendedor. Por isso o produto e acompanhado sem vendedor, e so quando
  aparece um sinal de oferta o robo abre a pagina do produto para confirmar preco e vendedor.
- O link de afiliado e montado com a tag: https://www.amazon.com.br/dp/<ASIN>?tag=<tag>
- Se a Amazon pedir CAPTCHA, a coleta da Amazon para neste ciclo. O robo nao resolve CAPTCHA.
"""
import random
import time
import urllib.parse

from .base import ErroDaFonte, Item

BASE = "https://www.amazon.com.br"

JS_BUSCA = r"""() => {
  const num = t => { if (!t) return 0;
    const n = parseFloat(t.replace(/[^\d.,]/g, '').replace(/\./g, '').replace(',', '.'));
    return isFinite(n) ? Math.round(n * 100) : 0; };
  const parcelas = (t) => { const m = (t || '').replace(/\s+/g, ' ').match(/(\d{1,2})\s*x\s*(?:de\s*)?R\$\s*([\d.]+,\d{2})(.{0,30})/i);
    return m ? m[1] + 'x de R$ ' + m[2] + (/sem juros/i.test(m[3]) ? ' sem juros' : '') : ''; };
  const cards = [...document.querySelectorAll('div[data-component-type="s-search-result"][data-asin]')]
    .filter(c => c.dataset.asin);
  return {
    captcha: !!document.querySelector('form[action*="validateCaptcha"], form[action*="/errors/validateCaptcha"]'),
    itens: cards.map(c => {
      const h = c.querySelector('h2'), p = c.querySelector('.a-price:not(.a-text-price) .a-offscreen'),
            de = c.querySelector('.a-price.a-text-price .a-offscreen'), img = c.querySelector('img.s-image');
      return { asin: c.dataset.asin, titulo: h ? (h.getAttribute('aria-label') || h.textContent).trim() : '',
               preco: num(p && p.textContent), de: num(de && de.textContent), imagem: img ? img.src : '',
               parcelas: parcelas(c.innerText) };
    })
  };
}"""

JS_PRODUTO = r"""() => {
  const num = t => { if (!t) return 0;
    const n = parseFloat(t.replace(/[^\d.,]/g, '').replace(/\./g, '').replace(',', '.'));
    return isFinite(n) ? Math.round(n * 100) : 0; };
  const txt = s => { const e = document.querySelector(s); return e ? e.textContent.replace(/\s+/g, ' ').trim() : ''; };
  const parcelas = (t) => { const m = (t || '').replace(/\s+/g, ' ').match(/(\d{1,2})\s*x\s*(?:de\s*)?R\$\s*([\d.]+,\d{2})(.{0,30})/i);
    return m ? m[1] + 'x de R$ ' + m[2] + (/sem juros/i.test(m[3]) ? ' sem juros' : '') : ''; };
  const vendedor = txt('#merchantInfoFeature_feature_div') ||
    [...document.querySelectorAll('[offer-display-feature-name="desktop-merchant-info"]')].map(e => e.textContent.replace(/\s+/g, ' ').trim()).join(' ');
  return {
    captcha: !!document.querySelector('form[action*="validateCaptcha"]'),
    vendedor: vendedor,
    preco: num(txt('#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen') || txt('#corePriceDisplay_desktop_feature_div .a-price .a-offscreen') || txt('.priceToPay')),
    de: num(txt('#corePriceDisplay_desktop_feature_div .basisPrice .a-offscreen') || txt('.basisPrice .a-offscreen')),
    parcelas: parcelas((document.querySelector('#apex_desktop, #corePriceDisplay_desktop_feature_div') || {}).innerText),
    estoque: txt('#availability').slice(0, 60)
  };
}"""


def converter(no, tag=""):
    """Um resultado da busca -> Item, ainda sem vendedor. None se nao tiver preco."""
    if not no.get("asin") or not no.get("preco") or not no.get("titulo"):
        return None
    url = f"{BASE}/dp/{no['asin']}"
    de = no.get("de") or 0
    return Item(loja="amazon", id_loja=no["asin"], titulo=no["titulo"], preco_cent=no["preco"],
                original_cent=de if de > no["preco"] else 0,    # valor menor que o preco e parcela, nao preco "de"
                url=url, url_afiliado=f"{url}?tag={tag}" if tag else "", imagem=no.get("imagem") or "",
                parcelas=no.get("parcelas") or "")


def nome_do_vendedor(texto):
    """'Enviado / Vendido Amazon.com.br Amazon.com.br ...' -> ('Amazon.com.br', 'oficial')."""
    if "amazon" in texto.lower():
        return "Amazon.com.br", "oficial"
    limpo = texto.replace("Enviado / Vendido", "").replace("Vendido por", "").replace("Enviado por", "").strip()
    palavras = limpo.split()
    for n in range(1, len(palavras) // 2 + 1):      # a pagina repete o nome: "Loja X Loja X"
        if palavras[:n] == palavras[n:2 * n]:
            limpo = " ".join(palavras[:n])
            break
    return (limpo[:60] or "vendedor nao identificado"), ""


class AmazonSite:
    nome = "amazon"
    verifica_vendedor = True

    def __init__(self, env, navegador, base=BASE, pausa=(4, 9)):
        self.tag = env.get("AMAZON_PARTNER_TAG", "")
        self.nav, self.base, self.pausa = navegador, base, pausa
        self.bloqueada = False

    def _esperar(self):
        if self.pausa:
            time.sleep(random.uniform(*self.pausa))

    def _ler(self, url, js):
        if self.bloqueada:
            raise ErroDaFonte("Amazon pediu verificacao (CAPTCHA) neste ciclo; coleta da Amazon interrompida")
        self.nav.ir(url)
        dados = self.nav.avaliar(js)
        if dados.get("captcha"):
            self.bloqueada = True
            raise ErroDaFonte("Amazon pediu verificacao (CAPTCHA); coleta da Amazon interrompida neste ciclo")
        return dados

    def url_busca(self, palavra, pagina=1):
        return f"{self.base}/s?" + urllib.parse.urlencode({"k": palavra, "page": pagina})

    def url_produto(self, asin):
        return f"{self.base}/dp/{asin}"

    def buscar_bruto(self, palavra, pagina=1, por_pagina=0):
        return self._ler(self.url_busca(palavra, pagina), JS_BUSCA)

    def buscar(self, palavra, paginas=1, por_pagina=0, pausa=0):
        itens = []
        for pagina in range(1, paginas + 1):
            nos = self.buscar_bruto(palavra, pagina)["itens"]
            itens += [i for i in (converter(no, self.tag) for no in nos) if i]
            if not nos:
                break
            self._esperar()
        return itens

    def verificar(self, item):
        """Abre a pagina do produto e devolve o item com vendedor, selo e preco confirmados."""
        d = self._ler(self.url_produto(item.id_loja), JS_PRODUTO)
        self._esperar()
        vendedor, selo = nome_do_vendedor(d.get("vendedor") or "")
        novo = Item(**item.__dict__)
        novo.vendedor, novo.selo = vendedor, selo
        if d.get("preco"):
            novo.preco_cent = d["preco"]
            novo.original_cent = d["de"] if (d.get("de") or 0) > d["preco"] else 0
        if d.get("parcelas"):
            novo.parcelas = d["parcelas"]
        return novo

    def fechar(self):
        self.nav.fechar()
