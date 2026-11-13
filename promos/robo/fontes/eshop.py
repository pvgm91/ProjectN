"""Nintendo eShop Brasil: pagina publica de ofertas da loja da Nintendo.

Nao usa chave. O robo abre https://www.nintendo.com/pt-br/store/sales-and-deals/ e le os
dados dos produtos que a propria pagina carrega (bloco __NEXT_DATA__). A pagina destaca
cerca de 100 ofertas por vez, nao a lista inteira de promocoes da eShop.
Nao ha programa de afiliados: o link do post e o da propria loja.
"""
import json
import re
import urllib.error
import urllib.request

from .base import ErroDaFonte, Item, para_centavos

PAGINA = "https://www.nintendo.com/pt-br/store/sales-and-deals/"
PRODUTO = "https://www.nintendo.com/pt-br/store/products/{}/"
IMAGEM = "https://assets.nintendo.com/image/upload/f_auto/q_auto/{}"
NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
BLOCO = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def extrair_produtos(html):
    """Acha, em qualquer profundidade do __NEXT_DATA__, os produtos com preco. Sem repetidos."""
    m = BLOCO.search(html)
    if not m:
        raise ErroDaFonte("eShop: a pagina mudou de formato (bloco __NEXT_DATA__ nao encontrado)")
    try:
        dados = json.loads(m.group(1))
    except ValueError:
        raise ErroDaFonte("eShop: nao foi possivel ler os dados da pagina")
    achados, pilha = {}, [dados]
    while pilha:
        o = pilha.pop()
        if isinstance(o, list):
            pilha.extend(o)
        elif isinstance(o, dict):
            if o.get("nsuid") and o.get("name") and isinstance(o.get("prices"), dict):
                achados.setdefault(str(o["nsuid"]), o)
            else:
                pilha.extend(o.values())
    return list(achados.values())


def converter(p):
    """Um produto da pagina -> Item. None se nao for jogo ou nao tiver preco."""
    if ((p.get("topLevelCategory") or {}).get("code") or "GAMES") != "GAMES":
        return None
    precos = p.get("prices") or {}
    preco = para_centavos(precos.get("finalPrice"))
    cheio = para_centavos(precos.get("regularPrice"))
    if not preco:
        return None
    url = PRODUTO.format(p["urlKey"]) if p.get("urlKey") else PAGINA
    imagem = (p.get("productImage") or {}).get("publicId") or ""
    return Item(
        loja="eshop", id_loja=str(p["nsuid"]), titulo=p["name"],
        preco_cent=preco, original_cent=cheio if cheio > preco else 0,
        url=url, url_afiliado=url,
        imagem=IMAGEM.format(imagem.lstrip("/")) if imagem else "",
        vendedor="Nintendo eShop", selo="oficial",
        categoria="Switch 2" if "2" in str(p.get("platformCode") or "") else "Switch",
        validade=((p.get("eshopDetails") or {}).get("discountPriceEnd") or "") if cheio > preco else "")


class Eshop:
    nome = "eshop"
    por_palavra = False       # uma pagina so por ciclo, sem busca por palavra-chave

    def __init__(self, env=None, baixar=None):
        self._baixar = baixar or self._baixar_http     # trocavel nos testes

    def _baixar_http(self):
        req = urllib.request.Request(PAGINA, headers={"User-Agent": NAVEGADOR, "Accept-Language": "pt-BR,pt;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise ErroDaFonte(f"eShop respondeu HTTP {e.code}")
        except urllib.error.URLError as e:
            raise ErroDaFonte(f"eShop inacessivel: {e.reason}")

    def buscar_bruto(self, *_):
        produtos = extrair_produtos(self._baixar())
        return {"total_na_pagina": len(produtos),
                "amostra": [{k: p.get(k) for k in ("name", "nsuid", "prices", "platformCode", "urlKey")} for p in produtos[:5]]}

    def coletar(self):
        return [i for i in (converter(p) for p in extrair_produtos(self._baixar())) if i]

    def buscar(self, *_):
        return self.coletar()
