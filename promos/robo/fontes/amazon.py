"""Amazon - Creators API (substituta da PA-API 5).

1. Token: POST JSON em api.amazon.com/auth/o2/token (credencial versao 3.1 = regiao NA, que inclui o Brasil)
   com grant_type=client_credentials e scope=creatorsapi::default. Vale 1 hora.
2. Busca: POST https://creatorsapi.amazon/catalog/v1/searchItems
   com Authorization: Bearer <token> e x-marketplace: www.amazon.com.br.
   Cada chamada devolve no maximo 10 itens; ha no maximo 10 paginas por busca.
"""
import json
import time
import urllib.error
import urllib.request

from .base import ErroDaFonte, Item, SemCredenciais, para_centavos

API = "https://creatorsapi.amazon/catalog/v1/"
TOKEN_POR_VERSAO = {
    "3.1": "https://api.amazon.com/auth/o2/token",      # NA: US, CA, MX, BR
    "3.2": "https://api.amazon.co.uk/auth/o2/token",    # EU
    "3.3": "https://api.amazon.co.jp/auth/o2/token",    # FE
}
RECURSOS = [
    "itemInfo.title", "images.primary.large",
    "offersV2.listings.price", "offersV2.listings.merchantInfo",
    "offersV2.listings.condition", "offersV2.listings.availability",
    "offersV2.listings.isBuyBoxWinner", "offersV2.listings.dealDetails",
]
MAX_POR_PAGINA = 10
MAX_PAGINAS = 10


def _valor(d, *caminho):
    for chave in caminho:
        if not isinstance(d, dict):
            return None
        d = d.get(chave)
    return d


def converter(no):
    """Um item de searchItems -> Item. None se nao houver oferta de produto novo em estoque."""
    ofertas = _valor(no, "offersV2", "listings") or []
    ofertas = [o for o in ofertas if (_valor(o, "condition", "value") or "New") == "New"]
    if not ofertas:
        return None
    oferta = next((o for o in ofertas if o.get("isBuyBoxWinner")), ofertas[0])
    if "OUT_OF_STOCK" in str(_valor(oferta, "availability", "type") or "").upper():
        return None
    preco = para_centavos(_valor(oferta, "price", "money", "amount"))
    if not preco:
        return None
    original = para_centavos(_valor(oferta, "price", "savingBasis", "money", "amount"))
    vendedor = _valor(oferta, "merchantInfo", "name") or ""
    url = no.get("detailPageURL") or ""
    return Item(
        loja="amazon", id_loja=str(no.get("asin")),
        titulo=_valor(no, "itemInfo", "title", "displayValue") or "",
        preco_cent=preco, original_cent=original if original > preco else 0,
        url=url, url_afiliado=url,     # detailPageURL ja vem com a tag de afiliado
        imagem=_valor(no, "images", "primary", "large", "url") or "",
        vendedor=vendedor,
        selo="oficial" if vendedor.lower().startswith("amazon") else "")


class Amazon:
    nome = "amazon"

    def __init__(self, env, enviar=None):
        self.id = env.get("AMAZON_CREDENTIAL_ID", "")
        self.segredo = env.get("AMAZON_CREDENTIAL_SECRET", "")
        self.tag = env.get("AMAZON_PARTNER_TAG", "")
        self.versao = (env.get("AMAZON_VERSION") or "3.1").lstrip("vV")
        self.marketplace = env.get("AMAZON_MARKETPLACE") or "www.amazon.com.br"
        self._enviar = enviar or self._enviar_http    # trocavel nos testes
        self._token, self._token_expira = "", 0
        if not (self.id and self.segredo):
            raise SemCredenciais("Amazon: preencha AMAZON_CREDENTIAL_ID e AMAZON_CREDENTIAL_SECRET no .env")
        if not self.tag:
            raise SemCredenciais("Amazon: falta AMAZON_PARTNER_TAG no .env (o ID de associado, ex.: projectn-20)")
        if self.versao not in TOKEN_POR_VERSAO:
            raise SemCredenciais(f"Amazon: versao de credencial '{self.versao}' desconhecida (use 3.1)")

    def _enviar_http(self, url, corpo, cabecalhos):
        req = urllib.request.Request(url, data=corpo.encode("utf-8"), headers=cabecalhos)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(texto)
            except ValueError:
                return e.code, {"message": texto[:300]}
        except urllib.error.URLError as e:
            raise ErroDaFonte(f"Amazon inacessivel: {e.reason}")

    def token(self):
        if self._token and time.time() < self._token_expira - 60:
            return self._token
        corpo = json.dumps({"grant_type": "client_credentials", "client_id": self.id,
                            "client_secret": self.segredo, "scope": "creatorsapi::default"})
        status, dados = self._enviar(TOKEN_POR_VERSAO[self.versao], corpo, {"Content-Type": "application/json"})
        if status != 200 or not dados.get("access_token"):
            motivo = dados.get("error_description") or dados.get("error") or dados.get("message") or dados
            raise ErroDaFonte(f"Amazon recusou as credenciais (HTTP {status}): {motivo}")
        self._token = dados["access_token"]
        self._token_expira = time.time() + int(dados.get("expires_in") or 3600)
        return self._token

    def chamar(self, operacao, parametros, tentativas=3):
        corpo = json.dumps({**parametros, "partnerTag": self.tag, "marketplace": self.marketplace},
                           ensure_ascii=False)
        for tentativa in range(tentativas):
            status, dados = self._enviar(API + operacao, corpo, {
                "Authorization": f"Bearer {self.token()}", "Content-Type": "application/json",
                "x-marketplace": self.marketplace})
            if status == 200:
                return dados
            if status == 429 and tentativa < tentativas - 1:      # limite de chamadas
                time.sleep(5 * (tentativa + 1))
                continue
            raise ErroDaFonte(f"Amazon HTTP {status}: {json.dumps(dados, ensure_ascii=False)[:400]}")
        return {}

    def buscar_bruto(self, palavra, pagina=1, por_pagina=MAX_POR_PAGINA):
        return self.chamar("searchItems", {
            "keywords": palavra, "itemCount": min(por_pagina, MAX_POR_PAGINA), "itemPage": pagina,
            "condition": "New", "resources": RECURSOS})

    def buscar(self, palavra, paginas=2, por_pagina=50, pausa=1.5):
        # A Amazon entrega 10 itens por chamada: para manter o mesmo volume das outras
        # lojas, o numero de paginas e convertido (ex.: 2 x 50 itens = 10 chamadas).
        total_paginas = min(MAX_PAGINAS, max(1, paginas * por_pagina // MAX_POR_PAGINA))
        itens = []
        for pagina in range(1, total_paginas + 1):
            resultado = self.buscar_bruto(palavra, pagina).get("searchResult") or {}
            nos = resultado.get("items") or []
            itens += [i for i in (converter(no) for no in nos) if i]
            if len(nos) < MAX_POR_PAGINA or pagina * MAX_POR_PAGINA >= int(resultado.get("totalResultCount") or 0):
                break
            time.sleep(pausa)
        return itens
