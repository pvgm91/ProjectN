"""Mercado Livre pelo site (sem API): o robo abre a busca num navegador ja logado e le os precos.

O site so mostra a busca para quem esta logado. Por isso e preciso entrar na conta UMA vez no
navegador do robo:  rodar.bat entrar mercadolivre-site   (o login fica guardado no perfil do robo).
Usado para a vitrine das lojas preferidas (ex.: busca "switch game hut") e para conferir cupons.
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
PAGINA_CUPONS = "https://www.mercadolivre.com.br/cupons"

# Procura cada codigo na pagina de cupons e devolve o texto do cartao em volta (regra, minimo, validade).
JS_CUPONS = r"""(codigos) => {
  const login = /account-verification|\/login|\/registration/.test(location.href);
  const folhas = [...document.querySelectorAll('body *')].filter(e => !e.children.length && e.textContent.trim());
  const achados = {};
  for (const cod of codigos) {
    const re = new RegExp('(^|[^A-Z0-9])' + cod.replace(/[^A-Z0-9]/gi, '') + '([^A-Z0-9]|$)', 'i');
    const el = folhas.find(e => re.test(e.textContent));
    if (!el) continue;
    let p = el;
    for (let k = 0; k < 8 && p.parentElement; k++) {
      p = p.parentElement;
      const t = p.innerText || '';
      if (t.length > 60 && /(v[aá]lid|vence|expira|at[eé]\s+\d|off|%|m[ií]nim)/i.test(t)) break;
    }
    achados[cod] = (p.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 400);
  }
  return { login: login, url: location.href, achados: achados,
           texto: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').slice(0, 4000) };
}"""
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
    titulo_pagina: document.title, tamanho_html: document.documentElement.outerHTML.length,
    texto: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').slice(0, 700),
    contagens: Object.fromEntries(['li.ui-search-layout__item', '.poly-card', '.ui-search-result', '[class*="poly-"]',
      'li[class*="ui-search"]', '.andes-money-amount__fraction', 'a[href*="MLB"]', 'iframe', 'form'].map(q => [q, document.querySelectorAll(q).length])),
    classes: [...new Set([...document.querySelectorAll('[class]')].flatMap(e => [...e.classList]))].filter(c => /search|poly|card|item|result/i.test(c)).slice(0, 80),
    amostra_link: (() => { const a = document.querySelector('a[href*="MLB"]'); if (!a) return ''; let e = a; for (let k = 0; k < 6 && e.parentElement; k++) e = e.parentElement; return e.outerHTML.replace(/\s+/g, ' ').slice(0, 5000); })(),
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
ITEM_NO_FILTRO = re.compile(r"item_id(?:%3A|:)(MLB\d+)", re.I)


def _sem_acento(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()


def nome_da_loja(vendedor, lojas):
    """'Por Gamer Hut' / 'Vendido por GAMER HUT' -> 'Gamer Hut' se for uma das lojas cadastradas, senao ''."""
    v = _sem_acento(vendedor).replace(" ", "")
    for nome in (lojas or {}).values():
        if _sem_acento(nome).replace(" ", "") in v:
            return nome
    return ""


def converter(no, lojas=None, afiliado=None):
    """Um card da busca -> Item. None se faltar titulo, preco ou identificador."""
    bruto = (no.get("url") or "").split("#")[0]
    url = bruto.split("?")[0]
    m = ID_NA_URL.search(url)
    if not (m and no.get("titulo") and no.get("preco")):
        return None
    filtro = ITEM_NO_FILTRO.search(bruto)
    if "/p/" in url and filtro:          # produto de catalogo: o link continua apontando para o anuncio desta loja
        url += "?pdp_filters=item_id%3A" + filtro.group(1).upper()
    de = no.get("de") or 0
    vendedor = re.sub(r"^(Vendido\s+)?Por\s+", "", no.get("vendedor") or "", flags=re.I).strip()
    loja = nome_da_loja(vendedor, lojas)
    if afiliado:
        from .mercadolivre import com_afiliado
        url_afiliado = com_afiliado(url, afiliado)
    else:
        url_afiliado = ""
    return Item(loja="mercadolivre", id_loja=m.group(1).replace("-", ""), titulo=no["titulo"],
                preco_cent=no["preco"], original_cent=de if de > no["preco"] else 0,
                url=url, url_afiliado=url_afiliado, imagem=no.get("imagem") or "",
                vendedor=loja or vendedor, selo="oficial" if (no.get("oficial") or loja) else "",
                nota=float(no.get("nota") or 0), vendas=int(no.get("avaliacoes") or 0),
                parcelas=no.get("parcelas") or "")


class MercadoLivreSite:
    nome = "mercadolivre"

    def __init__(self, env, navegador, base=BASE, pausa=(4, 9), lojas=None, afiliado=None, so_lojas=False):
        self.nav, self.base, self.pausa = navegador, base, pausa
        self.lojas, self.afiliado, self.so_lojas = lojas or {}, afiliado, so_lojas
        self.bloqueada = False

    def url_busca(self, palavra, pagina=1):
        caminho = urllib.parse.quote(palavra.strip().replace(" ", "-"))
        return f"{self.base}/{caminho}" + (f"_Desde_{(pagina - 1) * 48 + 1}_NoIndex_True" if pagina > 1 else "")

    def buscar_bruto(self, palavra, pagina=1, por_pagina=0):
        if self.bloqueada:
            raise ErroDaFonte("Mercado Livre pediu login neste ciclo; coleta interrompida")
        self.nav.ir(self.url_busca(palavra, pagina))
        self.nav.rolar()
        self.nav.esperar("li.ui-search-layout__item, .poly-card, .andes-money-amount__fraction")
        dados = self.nav.avaliar(JS_BUSCA)
        if dados.get("login"):
            self.bloqueada = True
            raise ErroDaFonte("Mercado Livre pediu login. Rode: rodar.bat entrar mercadolivre")
        if not dados.get("itens") and dados.get("tamanho_html", 0) < 20000:
            self.bloqueada = True      # pagina de erro curta no lugar da lista: o site recusou o navegador do robo
            raise ErroDaFonte("Mercado Livre recusou o navegador automatizado (pagina de erro no lugar da busca)")
        return dados

    def buscar(self, palavra, paginas=1, por_pagina=0, pausa=0):
        itens = []
        for pagina in range(1, max(1, paginas) + 1):
            nos = self.buscar_bruto(palavra, pagina)["itens"]
            itens += [i for i in (converter(no, self.lojas, self.afiliado) for no in nos) if i]
            if self.pausa:
                time.sleep(random.uniform(*self.pausa))
            if len(nos) < 40:          # ultima pagina
                break
        if self.so_lojas:              # vitrine: so os anuncios das lojas cadastradas (ex.: Gamer Hut)
            nomes = set(self.lojas.values())
            itens = [i for i in itens if i.vendedor in nomes]
        return itens

    def conferir_cupons(self, codigos):
        """Abre a pagina de cupons da conta e devolve {CODIGO: texto do cartao do cupom} dos codigos que aparecem la."""
        if self.bloqueada:
            raise ErroDaFonte("Mercado Livre pediu login neste ciclo")
        self.nav.ir(PAGINA_CUPONS)
        self.nav.esperar("main, #root-app", 10000)
        self.nav.rolar(6)
        dados = self.nav.avaliar_com(JS_CUPONS, list(codigos))
        if dados.get("login"):
            self.bloqueada = True
            raise ErroDaFonte("Mercado Livre pediu login. Rode: rodar.bat entrar mercadolivre-site")
        return dados

    def fechar(self):
        self.nav.fechar()
