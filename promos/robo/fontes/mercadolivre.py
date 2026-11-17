"""Mercado Livre pela API oficial de desenvolvedor (App ID e Secret Key no .env).

1. Token, em ordem de preferencia:
   - da sua conta: autorizado uma vez com 'rodar.bat entrar mercadolivre' e guardado em
     dados/ml_token.json; renovado sozinho com o refresh_token;
   - da aplicacao (client_credentials), se a conta ainda nao foi autorizada.
2. Coleta pelo CATALOGO, que e o que a API libera hoje (a busca de anuncios e a leitura de anuncio
   por codigo respondem 403 para aplicacoes novas):
   - as palavras-chave de catalogo.json em /products/search;
   - os links de produto de catalogo (.../p/MLB...) de config/lista_mercadolivre.txt;
   para cada produto, /products/{id}/items da o preco de quem esta vendendo (o "vencedor").
   Produto sem ninguem vendendo responde 404 e e ignorado.
3. Diagnostico (rodar.bat testar mercadolivre) testa tambem os caminhos fechados:
   a. /sites/MLB/search?q=...           anuncios, com preco, preco "de", parcelas e loja oficial
   b. /products/search + /products/{id}/items   catalogo (usado se a busca (a) estiver fechada)
   O robo descobre sozinho qual esta liberado para a aplicacao e guarda o modo na primeira busca.
- So passa na reputacao anuncio de loja oficial (regras.json).
- O link de afiliado nao vem da API: continua saindo do portal de afiliados.
"""
import json
import re
import time
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from .base import ErroDaFonte, Item, SemCredenciais, para_centavos

API = "https://api.mercadolibre.com"
AUTORIZACAO = "https://auth.mercadolivre.com.br/authorization"
REDIRECT_PADRAO = "https://www.projectn.com.br"


ID_ANUNCIO = re.compile(r"MLB-?(\d{3,})", re.I)
ID_CATALOGO = re.compile(r"/p/(MLB\d{3,})", re.I)
NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def e_link_de_afiliado(url):
    return "mercadolivre.com/sec/" in url or "matt_tool" in url or "matt_word" in url


def com_afiliado(url, afiliado):
    """Acrescenta a identificacao de afiliado (matt_word e matt_tool) ao link do produto.

    afiliado = {"matt_word": "projectn", "matt_tool": "75936721"}. Links que ja tem a
    identificacao, ou sem afiliado configurado, voltam como estao.
    """
    if not url or not afiliado or not afiliado.get("matt_tool") or e_link_de_afiliado(url):
        return url
    base = url.split("#")[0]
    partes = urllib.parse.urlsplit(base)
    consulta = [(k, v) for k, v in urllib.parse.parse_qsl(partes.query) if k not in ("matt_word", "matt_tool")]
    consulta += [("matt_word", afiliado.get("matt_word", "")), ("matt_tool", str(afiliado["matt_tool"]))]
    return urllib.parse.urlunsplit(partes._replace(query=urllib.parse.urlencode(consulta)))


def ler_lista(caminho):
    """Linhas validas (links) do arquivo da lista, sem comentarios nem repeticoes."""
    try:
        linhas = Path(caminho).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    vistos, saida = set(), []
    for l in linhas:
        l = l.strip()
        if l and not l.startswith("#") and "http" in l:
            l = l[l.index("http"):].split()[0]
            if l not in vistos:
                vistos.add(l)
                saida.append(l)
    return saida


def codigo_do_link(url):
    """('anuncio', 'MLB123') ou ('catalogo', 'MLB123') ou None, sem acessar a rede."""
    m = ID_CATALOGO.search(url)
    if m:
        return "catalogo", m.group(1).upper()
    m = re.search(r"(?:[?&#]wid=|item_id(?:%3A|:))(MLB\d{3,})", url, re.I)
    if m:
        return "anuncio", m.group(1).upper()
    m = ID_ANUNCIO.search(url)
    return ("anuncio", "MLB" + m.group(1)) if m else None


def _parcelas(inst):
    """{'quantity': 10, 'amount': 35.99, 'rate': 0} -> '10x de R$ 35,99 sem juros'."""
    if not isinstance(inst, dict) or not inst.get("quantity") or not inst.get("amount"):
        return ""
    cent = para_centavos(inst["amount"])
    valor = f"{cent // 100:,}".replace(",", ".") + f",{cent % 100:02d}"
    return f"{int(inst['quantity'])}x de R$ {valor}" + (" sem juros" if not inst.get("rate") else "")


def converter_anuncio(r):
    """Um resultado de /sites/MLB/search (ou de /items) -> Item."""
    preco = para_centavos(r.get("price"))
    if not (r.get("id") and r.get("title") and preco):
        return None
    de = para_centavos(r.get("original_price"))
    vendedor = (r.get("seller") or {}).get("nickname") or ""
    return Item(loja="mercadolivre", id_loja=str(r["id"]), titulo=r["title"], preco_cent=preco,
                original_cent=de if de > preco else 0, url=r.get("permalink") or "", url_afiliado="",
                imagem=(r.get("thumbnail") or "").replace("http://", "https://").replace("-I.jpg", "-O.jpg"),
                vendedor=vendedor, selo="oficial" if r.get("official_store_id") else "",
                parcelas=_parcelas(r.get("installments")))


def converter_catalogo(produto, anuncio, lojas=None):
    """Produto do catalogo + anuncio que vende ele (de /products/{id}/items) -> Item.

    O link aponta para a pagina do produto ja com ESSE anuncio escolhido (pdp_filters=item_id:...),
    para o preco do post ser o mesmo que a pessoa ve ao abrir.
    """
    preco = para_centavos(anuncio.get("price"))
    if not (produto.get("id") and produto.get("name") and preco):
        return None
    de = para_centavos(anuncio.get("original_price"))
    fotos = produto.get("pictures") or []
    return Item(loja="mercadolivre", id_loja=str(produto["id"]), titulo=produto["name"], preco_cent=preco,
                original_cent=de if de > preco else 0,
                url=f"https://www.mercadolivre.com.br/p/{produto['id']}"
                    + (f"?pdp_filters=item_id%3A{anuncio['item_id']}" if anuncio.get("item_id") else ""),
                url_afiliado="", imagem=(fotos[0].get("url") or "") if fotos else "",
                vendedor=(lojas or {}).get(str(anuncio.get("official_store_id")), ""),   # nome so das lojas cadastradas
                selo="oficial" if anuncio.get("official_store_id") else "",
                parcelas=_parcelas(anuncio.get("installments")))


class MercadoLivre:
    nome = "mercadolivre"
    por_palavra = False       # coleta pela lista, nao por palavra-chave

    def __init__(self, env, enviar=None, pausa=0.25, arquivo_token=None, lista=None, cache=None, resolver=None, afiliado=None,
                 buscas=None, por_busca=50, lojas=None):
        self.app_id = env.get("MERCADOLIVRE_APP_ID", "")
        self.segredo = env.get("MERCADOLIVRE_SECRET", "")
        self.redirect = env.get("MERCADOLIVRE_REDIRECT_URI") or REDIRECT_PADRAO
        self.arquivo_token = Path(arquivo_token) if arquivo_token else None
        self.tipo_token = ""
        self.lista = Path(lista) if lista else None
        self.cache = Path(cache) if cache else None
        self._resolver = resolver or self._resolver_http
        self.afiliado = afiliado or {}
        self.buscas = list(buscas or [])
        self.lojas = {str(k): v for k, v in (lojas or {}).items()}   # official_store_id -> nome
        self.por_busca = por_busca
        self.buscas_jogos, self.por_jogo = [], 5    # jogos da lista config/jogos.txt (rodizio), poucos resultados cada
        self.ignorados = []        # links da lista que a API nao deixa ler (anuncio solto, sem /p/)
        self._vistos_rodada = set()  # produto ja consultado nesta rodada (aparece em varias buscas)
        self.falhas = 0              # consultas que deram erro isolado e foram puladas
        self._enviar = enviar or self._enviar_http
        self.pausa = pausa
        self._token, self._expira = "", 0
        if not (self.app_id and self.segredo):
            raise SemCredenciais("Mercado Livre: preencha MERCADOLIVRE_APP_ID e MERCADOLIVRE_SECRET no .env")

    def _enviar_http(self, metodo, url, corpo=None, cabecalhos=None):
        dados = urllib.parse.urlencode(corpo).encode() if corpo else None
        req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8") or "{}")
            except ValueError:
                return e.code, {}
        except urllib.error.URLError as e:
            raise ErroDaFonte(f"Mercado Livre inacessivel: {e.reason}")

    def _pedir_token(self, corpo):
        st, d = self._enviar("POST", API + "/oauth/token", {"client_id": self.app_id, "client_secret": self.segredo, **corpo},
                             {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
        if st != 200 or not d.get("access_token"):
            raise ErroDaFonte(f"Mercado Livre recusou o pedido de acesso (HTTP {st}): {d.get('message') or d.get('error') or d}")
        return d

    def _ler_conta(self):
        try:
            return json.loads(self.arquivo_token.read_text(encoding="utf-8")) if self.arquivo_token and self.arquivo_token.exists() else None
        except (OSError, ValueError):
            return None

    def _guardar_conta(self, d):
        dados = {"access_token": d["access_token"], "refresh_token": d.get("refresh_token", ""),
                 "expira": time.time() + int(d.get("expires_in") or 21600), "user_id": d.get("user_id")}
        if self.arquivo_token:
            self.arquivo_token.write_text(json.dumps(dados), encoding="utf-8")
        return dados

    def url_autorizacao(self):
        return AUTORIZACAO + "?" + urllib.parse.urlencode({"response_type": "code", "client_id": self.app_id, "redirect_uri": self.redirect})

    def autorizar(self, texto_colado):
        """Recebe o endereco para onde o Mercado Livre redirecionou (ou so o codigo) e guarda o acesso da conta."""
        texto = texto_colado.strip()
        if texto.startswith("http"):
            codigo = urllib.parse.parse_qs(urllib.parse.urlparse(texto).query).get("code", [""])[0]
        else:
            codigo = texto
        if not codigo or not codigo.upper().startswith("TG-"):
            raise ErroDaFonte("nao encontrei o codigo no que foi colado. Cole o endereco que aparece na barra "
                              "depois de clicar em Permitir (ele tem '?code=TG-...')")
        d = self._pedir_token({"grant_type": "authorization_code", "code": codigo, "redirect_uri": self.redirect})
        return self._guardar_conta(d)

    def token(self):
        if self._token and time.time() < self._expira - 120:
            return self._token
        conta = self._ler_conta()
        if conta and conta.get("access_token"):
            if time.time() >= conta.get("expira", 0) - 120:
                if not conta.get("refresh_token"):
                    raise ErroDaFonte("o acesso da conta expirou: rode 'rodar.bat entrar mercadolivre' de novo")
                conta = self._guardar_conta(self._pedir_token({"grant_type": "refresh_token", "refresh_token": conta["refresh_token"]}))
            self._token, self._expira, self.tipo_token = conta["access_token"], conta["expira"], "conta"
            return self._token
        d = self._pedir_token({"grant_type": "client_credentials"})
        self._token, self._expira, self.tipo_token = d["access_token"], time.time() + int(d.get("expires_in") or 21600), "aplicacao"
        return self._token

    def get(self, caminho, params=None):
        url = API + caminho + ("?" + urllib.parse.urlencode(params) if params else "")
        for tentativa in range(3):
            st, d = self._enviar("GET", url, None, {"Accept": "application/json", "Authorization": f"Bearer {self.token()}"})
            if st == 429 and tentativa < 2:
                time.sleep(4 * (tentativa + 1))
                continue
            return st, d
        return st, d

    def _resumo(self, st, d):
        return {"status": st, "mensagem": d.get("message") or d.get("error") or "",
                "chaves": list(d)[:15] if isinstance(d, dict) else [],
                "amostra": json.dumps((d.get("results") or [None])[0] if isinstance(d, dict) else d, ensure_ascii=False)[:1500]}

    def diagnosticar(self, palavra):
        """Testa cada caminho e devolve o que respondeu (sem segredos). Usado por 'rodar.bat testar'."""
        self.token()
        saida = {"acesso": self.tipo_token}
        st, d = self.get("/sites/MLB/search", {"q": palavra, "limit": 3})
        saida["busca"] = self._resumo(st, d)
        st, d = self.get("/products/search", {"status": "active", "site_id": "MLB", "q": palavra, "limit": 3})
        saida["catalogo"] = self._resumo(st, d)
        primeiro = ((d.get("results") or [{}])[0] or {}).get("id") if st == 200 else None
        if primeiro:
            st2, d2 = self.get(f"/products/{primeiro}/items")
            saida["catalogo_itens"] = self._resumo(st2, d2)
        return saida

    def item_do_catalogo(self, produto, link=""):
        """Le quem esta vendendo o produto e devolve o Item, ou None se ninguem vende (404)."""
        st, d = self.get(f"/products/{produto['id']}/items")
        if st == 404:
            return None
        if st in (401, 403):        # acesso perdido: vale para todos os produtos, entao para a coleta
            raise ErroDaFonte(f"Mercado Livre recusou a consulta de produtos (HTTP {st}): "
                              f"{d.get('message', '') if isinstance(d, dict) else ''}")
        if st not in (200, 206) or not isinstance(d, dict):   # 206 = resposta parcial, mas com os vendedores
            self.falhas += 1        # erro so deste produto: pula e segue
            return None
        anuncios = [a for a in (d.get("results") or []) if (a.get("condition") or "new") == "new"]
        if not anuncios:
            return None
        # Prioridade: loja cadastrada em mercadolivre_lojas (ex.: Gamer Hut), depois loja oficial, depois o resto;
        # dentro do grupo, o menor preco.
        preferidas = [a for a in anuncios if str(a.get("official_store_id")) in self.lojas]
        oficiais = [a for a in anuncios if a.get("official_store_id")]
        melhor = min(preferidas or oficiais or anuncios, key=lambda a: a.get("price") or 1e12)
        if not produto.get("name"):
            st2, prod = self.get(f"/products/{produto['id']}")
            produto = prod if st2 in (200, 206) and isinstance(prod, dict) else produto
        item = converter_catalogo(produto, melhor, self.lojas)
        if item:
            item.url_afiliado = link if e_link_de_afiliado(link) else com_afiliado(item.url, self.afiliado)
        return item

    def _sem_vendedor(self):
        """Produtos que estavam sem ninguem vendendo, com a hora da consulta (pulados por 24h)."""
        return self._ler_cache().get("__sem_vendedor__", {})

    def _marcar_sem_vendedor(self, pids):
        if not (self.cache and pids):
            return
        cache = self._ler_cache()
        agora = time.time()
        marcados = {k: v for k, v in cache.get("__sem_vendedor__", {}).items() if agora - v < 86400}
        marcados.update({p: agora for p in pids})
        cache["__sem_vendedor__"] = marcados
        self.cache.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def _buscar_catalogo(self, palavra, limite):
        """Ate 'limite' produtos do catalogo para a palavra, em paginas de 50."""
        produtos, offset = [], 0
        while len(produtos) < limite:
            st, d = self.get("/products/search", {"status": "active", "site_id": "MLB", "q": palavra,
                                                  "limit": min(50, limite - len(produtos)), "offset": offset})
            if st in (401, 403):
                raise ErroDaFonte(f"Mercado Livre: a busca de catalogo respondeu HTTP {st}: {d.get('message', '')}")
            if st not in (200, 206):
                self.falhas += 1        # so esta palavra falhou: segue com as outras
                break
            pagina = d.get("results") or []
            produtos += pagina
            offset += len(pagina)
            total = (d.get("paging") or {}).get("total") or 0
            if not pagina or offset >= total:
                break
        agora, sem = time.time(), self._sem_vendedor()
        itens, novos_sem = [], []
        for produto in produtos:
            pid = produto.get("id")
            if not pid or pid in self._vistos_rodada or agora - sem.get(pid, 0) < 86400:
                continue
            self._vistos_rodada.add(pid)
            time.sleep(self.pausa)
            item = self.item_do_catalogo(produto)
            if item:
                itens.append(item)
            else:
                novos_sem.append(pid)
        self._marcar_sem_vendedor(novos_sem)
        return itens

    # ------------------------------------------------------------ lista de acompanhamento

    def _resolver_http(self, url):
        """Segue o redirecionamento de um link curto (ex.: de afiliado) e devolve o endereco final."""
        req = urllib.request.Request(url, headers={"User-Agent": NAVEGADOR})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.geturl()
        except urllib.error.HTTPError as e:      # a pagina final pode recusar o robo; o endereco ja basta
            return e.geturl() or url
        except urllib.error.URLError:
            return url

    def _ler_cache(self):
        try:
            return json.loads(self.cache.read_text(encoding="utf-8")) if self.cache and self.cache.exists() else {}
        except (OSError, ValueError):
            return {}

    def entradas(self):
        """[(link_colado, tipo, codigo)] da lista. Links curtos sao resolvidos uma vez e guardados no cache."""
        cache, mudou, saida = self._ler_cache(), False, []
        cache.setdefault("__sem_vendedor__", {})
        for link in ler_lista(self.lista) if self.lista else []:
            achado = codigo_do_link(link)
            if not achado:
                if link not in cache:
                    cache[link] = codigo_do_link(self._resolver(link))
                    mudou = True
                achado = cache[link]
            if achado:
                saida.append((link, achado[0], achado[1]))
        if mudou and self.cache:
            self.cache.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return saida

    def coletar(self):
        """Uma rodada: palavras-chave no catalogo e depois os produtos da lista (a lista prevalece)."""
        por_id, self._vistos_rodada, self.falhas = {}, set(), 0
        for palavra in self.buscas:
            for item in self._buscar_catalogo(palavra, self.por_busca):
                por_id.setdefault(item.id_loja, item)
        for palavra in self.buscas_jogos:
            for item in self._buscar_catalogo(palavra, self.por_jogo):
                por_id.setdefault(item.id_loja, item)
        for item in self.coletar_lista():
            por_id[item.id_loja] = item
        return list(por_id.values())

    def coletar_lista(self):
        lidos, self.ignorados = {}, []
        for link, tipo, codigo in self.entradas():
            if tipo != "catalogo":
                self.ignorados.append(link)
                continue
            if codigo in lidos:
                continue
            time.sleep(self.pausa)
            item = self.item_do_catalogo({"id": codigo}, link)
            if item:
                item.selo = item.selo or "lista"     # escolhido por voce: passa na reputacao mesmo sem loja oficial
                lidos[codigo] = item
        return list(lidos.values())

    def buscar_bruto(self, palavra, pagina=1, por_pagina=10):
        d = self.diagnosticar(palavra)
        entradas = self.entradas()
        d["lista"] = {"links": len(entradas), "anuncios": sum(e[1] == "anuncio" for e in entradas),
                      "catalogo": sum(e[1] == "catalogo" for e in entradas),
                      "codigos": [e[2] for e in entradas][:20]}
        anuncios = [e[2] for e in entradas if e[1] == "anuncio"][:3]
        if anuncios:
            st, r = self.get("/items", {"ids": ",".join(anuncios)})
            d["lista"]["consulta_items"] = {"status": st, "amostra": json.dumps(r, ensure_ascii=False)[:1500]}
        catalogo = [e[2] for e in entradas if e[1] == "catalogo"][:1]
        if catalogo:
            st, r = self.get(f"/products/{catalogo[0]}/items")
            d["lista"]["consulta_catalogo"] = {"status": st, "amostra": json.dumps(r, ensure_ascii=False)[:1500]}
        return d

    def buscar(self, palavra, paginas=1, por_pagina=50, pausa=0):
        """Usado pelo teste: busca a palavra no catalogo e le os produtos da lista."""
        por_id = {i.id_loja: i for i in self._buscar_catalogo(palavra, min(por_pagina, 10))}
        for item in self.coletar_lista():
            por_id[item.id_loja] = item
        return list(por_id.values())
