"""Shopee Afiliados - Open API (GraphQL).

Autenticacao: cabecalho
    Authorization: SHA256 Credential={app_id}, Timestamp={ts}, Signature={assinatura}
onde assinatura = sha256(app_id + ts + corpo_da_requisicao + secret), ts em segundos.
"""
import hashlib
import json
import time
import urllib.error
import urllib.request

from .base import ErroDaFonte, Item, SemCredenciais, para_centavos

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
CODIGO_LIMITE_DE_CHAMADAS = 10030

CAMPOS = ("itemId productName priceMin priceMax price sales ratingStar priceDiscountRate "
          "imageUrl shopId shopName shopType productLink offerLink commissionRate")

# shopType: 1 = loja oficial (Mall); 2 e 4 = loja indicada (Star / Star+)
SELOS = {1: "oficial", 2: "indicada", 4: "indicada"}


def assinar(app_id, secret, corpo, ts):
    assinatura = hashlib.sha256(f"{app_id}{ts}{corpo}{secret}".encode("utf-8")).hexdigest()
    return f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={assinatura}"


def montar_consulta(palavra, pagina, limite):
    # sortType 2 = mais vendidos: privilegia anuncios com historico de venda
    return ("{ productOfferV2(keyword: %s, sortType: 2, page: %d, limit: %d) "
            "{ nodes { %s } pageInfo { page limit hasNextPage } } }"
            % (json.dumps(palavra, ensure_ascii=False), pagina, limite, CAMPOS))


def converter(no):
    """Um no de productOfferV2 -> Item. Devolve None se nao tiver preco."""
    preco = para_centavos(no.get("priceMin") or no.get("price"))
    if not preco:
        return None
    taxa = float(no.get("priceDiscountRate") or 0)          # percentual inteiro, ex.: 23
    original = int(round(preco / (1 - taxa / 100))) if 0 < taxa < 100 else 0
    tipos = no.get("shopType") or []
    if isinstance(tipos, int):
        tipos = [tipos]
    selo = ""
    for t in tipos:
        if SELOS.get(t) == "oficial":
            selo = "oficial"
            break
        selo = SELOS.get(t, selo)
    return Item(
        loja="shopee", id_loja=str(no.get("itemId")), titulo=no.get("productName") or "",
        preco_cent=preco, original_cent=original,
        url=no.get("productLink") or "", url_afiliado=no.get("offerLink") or "",
        imagem=no.get("imageUrl") or "", vendedor=no.get("shopName") or "", selo=selo,
        nota=float(no.get("ratingStar") or 0), vendas=int(no.get("sales") or 0),
        comissao_pct=round(float(no.get("commissionRate") or 0) * 100, 2))


class Shopee:
    nome = "shopee"

    def __init__(self, env, enviar=None):
        self.app_id = env.get("SHOPEE_APP_ID", "")
        self.secret = env.get("SHOPEE_SECRET", "")
        self._enviar = enviar or self._enviar_http   # trocavel nos testes
        if not (self.app_id and self.secret):
            raise SemCredenciais("Shopee: preencha SHOPEE_APP_ID e SHOPEE_SECRET no arquivo .env")

    def _enviar_http(self, corpo, cabecalhos):
        req = urllib.request.Request(ENDPOINT, data=corpo.encode("utf-8"), headers=cabecalhos)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ErroDaFonte(f"Shopee respondeu HTTP {e.code}: {e.read()[:300]!r}")
        except urllib.error.URLError as e:
            raise ErroDaFonte(f"Shopee inacessivel: {e.reason}")

    def chamar(self, consulta, tentativas=3):
        corpo = json.dumps({"query": consulta}, ensure_ascii=False)
        for tentativa in range(tentativas):
            ts = int(time.time())
            dados = self._enviar(corpo, {"Content-Type": "application/json",
                                         "Authorization": assinar(self.app_id, self.secret, corpo, ts)})
            erros = dados.get("errors")
            if not erros:
                return dados.get("data") or {}
            codigo = (erros[0].get("extensions") or {}).get("code")
            if codigo == CODIGO_LIMITE_DE_CHAMADAS and tentativa < tentativas - 1:
                time.sleep(5 * (tentativa + 1))
                continue
            raise ErroDaFonte(f"Shopee erro {codigo}: {erros[0].get('message')}")
        return {}

    def buscar_bruto(self, palavra, pagina=1, por_pagina=10):
        return self.chamar(montar_consulta(palavra, pagina, por_pagina))

    def buscar(self, palavra, paginas=2, por_pagina=50, pausa=1.5):
        itens = []
        for pagina in range(1, paginas + 1):
            dados = self.chamar(montar_consulta(palavra, pagina, por_pagina))
            bloco = dados.get("productOfferV2") or {}
            for no in bloco.get("nodes") or []:
                item = converter(no)
                if item:
                    itens.append(item)
            if not (bloco.get("pageInfo") or {}).get("hasNextPage"):
                break
            time.sleep(pausa)
        return itens
