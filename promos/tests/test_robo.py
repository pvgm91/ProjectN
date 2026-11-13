"""Testes do robo. Rodar dentro de promos:  py -3 -m unittest discover -s tests -v"""
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from robo import catalogo as cat, config, db, detector, exportar, painel, reputacao  # noqa: E402
from robo.coletor import processar  # noqa: E402
from robo.fontes import amazon, amazon_site, eshop, mercadolivre_site, shopee  # noqa: E402
from robo.navegador import Navegador  # noqa: E402

try:
    import playwright  # noqa: F401
    TEM_PLAYWRIGHT = True
except ImportError:
    TEM_PLAYWRIGHT = False
PAGINAS = Path(__file__).parent / "paginas"
from robo.fontes.base import ErroDaFonte, Item, SemCredenciais, para_centavos  # noqa: E402

CATALOGO = config.carregar_json("catalogo.json")
REGRAS = config.carregar_json("regras.json")
AMOSTRA = json.loads((Path(__file__).parent / "amostra_shopee.json").read_text(encoding="utf-8"))
AGORA = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)


def item(**k):
    base = dict(loja="shopee", id_loja="1", titulo="Jogo Teste Nintendo Switch 2", preco_cent=20000,
                original_cent=0, selo="oficial", nota=4.9, vendas=500, url="https://example.com/p")
    base.update(k)
    return Item(**base)


class Centavos(unittest.TestCase):
    def test_formatos(self):
        self.assertEqual(para_centavos("175.17"), 17517)
        self.assertEqual(para_centavos("175,17"), 17517)
        self.assertEqual(para_centavos("R$ 1.234,56"), 123456)
        self.assertEqual(para_centavos(227.38), 22738)
        self.assertEqual(para_centavos(""), 0)
        self.assertEqual(para_centavos("abc"), 0)

    def test_reais(self):
        self.assertEqual(exportar.reais(17517), "R$ 175,17")
        self.assertEqual(exportar.reais(123456), "R$ 1.234,56")


class Catalogo(unittest.TestCase):
    def test_aceita_universo_nintendo(self):
        self.assertEqual(cat.classificar("Sonic X Shadow Generations - Nintendo Switch 2", CATALOGO), "Switch 2")
        self.assertEqual(cat.classificar("Controle Joy-Con (par) Nintendo Switch", CATALOGO), "Switch")
        self.assertEqual(cat.classificar("LEGO Super Mário Aventuras", CATALOGO), "LEGO")
        self.assertEqual(cat.classificar("Amiibo Link Zelda", CATALOGO), "amiibo")
        self.assertEqual(cat.classificar("Controle 8BitDo Pro 2 para Switch", CATALOGO), "Acessorios")

    def test_recusa_fora_do_tema(self):
        self.assertIsNone(cat.classificar("Switch de Rede Gigabit 8 portas", CATALOGO))
        self.assertIsNone(cat.classificar("Armário 3 portas", CATALOGO))       # 'mario' dentro de 'armario'
        self.assertIsNone(cat.classificar("LEGO City Caminhão de Bombeiros", CATALOGO))
        self.assertIsNone(cat.classificar("Teclado mecânico switch blue", CATALOGO))
        self.assertIsNone(cat.classificar("Nintendo Switch OLED usado", CATALOGO))

    def test_identifica_produto_e_ignora_exemplo(self):
        self.assertEqual(cat.identificar_produto("Mario Kart World Switch 2", CATALOGO), ("", 0))
        c = {"produtos": [{"chave": "mkw", "termos": ["mario kart world"], "preco_sugerido_reais": 499.9}]}
        self.assertEqual(cat.identificar_produto("Jogo Mario Kart World - Switch 2", c), ("mkw", 49990))
        self.assertEqual(cat.identificar_produto("Mario Kart 8 Deluxe", c), ("", 0))


class Reputacao(unittest.TestCase):
    def test_shopee(self):
        self.assertTrue(reputacao.aprovado(item(), REGRAS)[0])
        self.assertFalse(reputacao.aprovado(item(selo=""), REGRAS)[0])
        self.assertFalse(reputacao.aprovado(item(nota=4.2), REGRAS)[0])
        self.assertFalse(reputacao.aprovado(item(nota=0), REGRAS)[0])
        self.assertFalse(reputacao.aprovado(item(vendas=3), REGRAS)[0])

    def test_mercadolivre_exige_selo(self):
        self.assertFalse(reputacao.aprovado(item(loja="mercadolivre", selo="", nota=0, vendas=0), REGRAS)[0])
        self.assertTrue(reputacao.aprovado(item(loja="mercadolivre", selo="oficial", nota=0, vendas=0), REGRAS)[0])


class Detector(unittest.TestCase):
    def test_desconto_da_loja_no_primeiro_dia(self):
        s = detector.detectar(17517, 22738, 0, [], [], REGRAS)
        self.assertEqual([x["tipo"] for x in s], ["desconto_loja"])
        self.assertEqual(s[0]["pct"], 23.0)            # o exemplo do grupo: 227,38 -> 175,17

    def test_desconto_pequeno_nao_dispara(self):
        self.assertEqual(detector.detectar(21000, 22738, 0, [], [], REGRAS), [])

    def test_preco_sugerido(self):
        s = detector.detectar(39900, 0, 49990, [], [], REGRAS)
        self.assertEqual(s[0]["tipo"], "preco_sugerido")
        self.assertEqual(s[0]["pct"], 20.2)

    def test_entre_lojas(self):
        s = detector.detectar(40000, 0, 0, [46000, 48000], [], REGRAS)
        self.assertEqual(s[0]["tipo"], "entre_lojas")
        self.assertEqual(s[0]["referencia_cent"], 47000)
        self.assertEqual(detector.detectar(45000, 0, 0, [46000, 48000], [], REGRAS), [])

    def test_historico_so_depois_do_minimo_de_dias(self):
        self.assertEqual(detector.detectar(15000, 0, 0, [], [20000] * 6, REGRAS), [])
        s = detector.detectar(15000, 0, 0, [], [20000] * 7, REGRAS)
        self.assertEqual(s[0]["tipo"], "historico")
        self.assertEqual(s[0]["pct"], 25.0)
        self.assertIn("menor preco em 7 dias", s[0]["texto"])

    def test_historico_desmascara_desconto_inflado(self):
        # loja diz "de 300 por 200", mas o produto sempre custou 200
        s = detector.detectar(20000, 30000, 0, [], [20000] * 10, REGRAS)
        self.assertEqual([x["tipo"] for x in s], ["desconto_loja"])   # historico NAO confirma

    def test_preco_minimo(self):
        self.assertEqual(detector.detectar(1990, 3980, 0, [], [], REGRAS), [])

    def test_ordem_do_mais_forte(self):
        s = detector.detectar(15000, 20000, 0, [], [30000] * 8, REGRAS)
        self.assertEqual([x["tipo"] for x in s], ["historico", "desconto_loja"])


class Shopee(unittest.TestCase):
    def test_assinatura(self):
        esperado = hashlib.sha256(b"1231700000000{\"query\":\"x\"}segredo").hexdigest()
        self.assertEqual(shopee.assinar("123", "segredo", '{"query":"x"}', 1700000000),
                         f"SHA256 Credential=123, Timestamp=1700000000, Signature={esperado}")

    def test_consulta_escapa_aspas(self):
        q = shopee.montar_consulta('jogo "switch"', 2, 50)
        self.assertIn('keyword: "jogo \\"switch\\""', q)
        self.assertIn("page: 2, limit: 50", q)

    def test_converter(self):
        no = AMOSTRA["data"]["productOfferV2"]["nodes"][0]
        i = shopee.converter(no)
        self.assertEqual((i.loja, i.id_loja, i.preco_cent, i.selo), ("shopee", "1001", 34990, "oficial"))
        self.assertEqual(i.original_cent, 44859)        # 349,90 / (1 - 0,22)
        self.assertEqual((i.nota, i.vendas, i.comissao_pct), (4.9, 820, 4.0))
        self.assertIsNone(shopee.converter({"itemId": 1, "productName": "x"}))
        self.assertEqual(shopee.converter({"itemId": 1, "priceMin": "10", "shopType": [2, 4]}).selo, "indicada")
        self.assertEqual(shopee.converter({"itemId": 1, "priceMin": "10", "shopType": None}).selo, "")

    def test_sem_credenciais(self):
        with self.assertRaises(SemCredenciais):
            shopee.Shopee({})

    def test_busca_com_resposta_simulada(self):
        chamadas = []

        def enviar(corpo, cabecalhos):
            chamadas.append((corpo, cabecalhos))
            return AMOSTRA

        itens = shopee.Shopee({"SHOPEE_APP_ID": "1", "SHOPEE_SECRET": "s"}, enviar=enviar).buscar("switch", 3, 50, 0)
        self.assertEqual(len(itens), 7)
        self.assertEqual(len(chamadas), 1)              # hasNextPage false: nao pede a pagina 2
        self.assertTrue(chamadas[0][1]["Authorization"].startswith("SHA256 Credential=1, Timestamp="))

    def test_erro_da_api(self):
        def enviar(corpo, cabecalhos):
            return {"errors": [{"message": "Invalid Signature", "extensions": {"code": 10020}}]}

        with self.assertRaises(ErroDaFonte) as e:
            shopee.Shopee({"SHOPEE_APP_ID": "1", "SHOPEE_SECRET": "s"}, enviar=enviar).buscar("switch")
        self.assertIn("10020", str(e.exception))

ENV_AMAZON = {"AMAZON_CREDENTIAL_ID": "id", "AMAZON_CREDENTIAL_SECRET": "seg", "AMAZON_PARTNER_TAG": "tag-20",
              "AMAZON_VERSION": "v3.1"}


def no_amazon(asin="B0TESTE001", preco=175.17, de=227.38, vendedor="Amazon.com.br", **extra):
    preco_d = {"money": {"amount": preco, "currency": "BRL"}}
    if de:
        preco_d["savingBasis"] = {"money": {"amount": de, "currency": "BRL"}}
    oferta = {"isBuyBoxWinner": True, "condition": {"value": "New"}, "availability": {"type": "IN_STOCK"},
              "merchantInfo": {"name": vendedor}, "price": preco_d}
    oferta.update(extra)
    return {"asin": asin, "detailPageURL": f"https://www.amazon.com.br/dp/{asin}?tag=tag-20",
            "itemInfo": {"title": {"displayValue": "Jogo Teste - Nintendo Switch 2"}},
            "images": {"primary": {"large": {"url": "https://example.com/i.jpg"}}},
            "offersV2": {"listings": [oferta]}}


class Amazon(unittest.TestCase):
    def test_converter(self):
        i = amazon.converter(no_amazon())
        self.assertEqual((i.loja, i.id_loja, i.preco_cent, i.original_cent, i.selo),
                         ("amazon", "B0TESTE001", 17517, 22738, "oficial"))
        self.assertEqual(i.url_afiliado, "https://www.amazon.com.br/dp/B0TESTE001?tag=tag-20")
        self.assertEqual(amazon.converter(no_amazon(vendedor="Loja Terceira")).selo, "")
        self.assertEqual(amazon.converter(no_amazon(de=None)).original_cent, 0)

    def test_converter_descarta_sem_oferta_usado_e_sem_estoque(self):
        self.assertIsNone(amazon.converter({"asin": "X", "offersV2": None}))
        self.assertIsNone(amazon.converter(no_amazon(condition={"value": "Used"})))
        self.assertIsNone(amazon.converter(no_amazon(availability={"type": "OUT_OF_STOCK"})))

    def test_credenciais_incompletas(self):
        with self.assertRaises(SemCredenciais):
            amazon.Amazon({})
        with self.assertRaises(SemCredenciais) as e:
            amazon.Amazon({"AMAZON_CREDENTIAL_ID": "a", "AMAZON_CREDENTIAL_SECRET": "b"})
        self.assertIn("AMAZON_PARTNER_TAG", str(e.exception))

    def test_busca_pede_token_uma_vez_e_pagina(self):
        chamadas = []

        def enviar(url, corpo, cab):
            chamadas.append((url, json.loads(corpo), cab))
            if url.endswith("/token"):
                return 200, {"access_token": "T", "expires_in": 3600}
            pagina = json.loads(corpo)["itemPage"]
            n = 10 if pagina == 1 else 3
            return 200, {"searchResult": {"totalResultCount": 13,
                                          "items": [no_amazon(asin=f"A{pagina}{k}") for k in range(n)]}}

        itens = amazon.Amazon(ENV_AMAZON, enviar=enviar).buscar("switch", 2, 50, 0)
        self.assertEqual(len(itens), 13)
        urls = [c[0] for c in chamadas]
        self.assertEqual(urls, ["https://api.amazon.com/auth/o2/token"] + ["https://creatorsapi.amazon/catalog/v1/searchItems"] * 2)
        self.assertEqual(chamadas[0][1]["scope"], "creatorsapi::default")
        corpo, cab = chamadas[1][1], chamadas[1][2]
        self.assertEqual((corpo["partnerTag"], corpo["marketplace"], corpo["itemCount"]), ("tag-20", "www.amazon.com.br", 10))
        self.assertEqual((cab["Authorization"], cab["x-marketplace"]), ("Bearer T", "www.amazon.com.br"))

    def test_erros(self):
        def token_ruim(url, corpo, cab):
            return 401, {"error": "invalid_client", "error_description": "Client authentication failed"}

        with self.assertRaises(ErroDaFonte) as e:
            amazon.Amazon(ENV_AMAZON, enviar=token_ruim).buscar("x")
        self.assertIn("Client authentication failed", str(e.exception))
        self.assertNotIn("seg", str(e.exception))

        def nao_elegivel(url, corpo, cab):
            if url.endswith("/token"):
                return 200, {"access_token": "T"}
            return 403, {"errors": [{"code": "AssociateNotEligible", "message": "nao elegivel"}]}

        with self.assertRaises(ErroDaFonte) as e:
            amazon.Amazon(ENV_AMAZON, enviar=nao_elegivel).buscar("x")
        self.assertIn("AssociateNotEligible", str(e.exception))

    def test_so_vendido_pela_amazon_passa_na_reputacao(self):
        self.assertTrue(reputacao.aprovado(amazon.converter(no_amazon()), REGRAS)[0])
        self.assertFalse(reputacao.aprovado(amazon.converter(no_amazon(vendedor="Terceiro")), REGRAS)[0])


def produto_eshop(nsuid="70010000000001", nome="Jogo Teste", final=112.84, cheio=161.2, **extra):
    p = {"nsuid": nsuid, "name": nome, "urlKey": "jogo-teste-switch", "platformCode": "NINTENDO_SWITCH",
         "topLevelCategory": {"code": "GAMES"}, "productImage": {"publicId": "store/x/abc"},
         "eshopDetails": {"discountPriceEnd": "2026-11-19T07:59:59Z"},
         "prices": {"finalPrice": final, "regularPrice": cheio, "discounted": True, "percentOff": 30}}
    p.update(extra)
    return p


def pagina_eshop(produtos):
    dados = {"props": {"pageProps": {"page": {"content": {"merchandisedGrid": produtos, "outra": [{"lista": produtos}]}}}}}
    return '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps(dados) + "</script></html>"


class EshopTestes(unittest.TestCase):
    def test_converter(self):
        i = eshop.converter(produto_eshop())
        self.assertEqual((i.loja, i.id_loja, i.preco_cent, i.original_cent, i.categoria, i.selo),
                         ("eshop", "70010000000001", 11284, 16120, "Switch", "oficial"))
        self.assertEqual(i.url, "https://www.nintendo.com/pt-br/store/products/jogo-teste-switch/")
        self.assertEqual(i.imagem, "https://assets.nintendo.com/image/upload/f_auto/q_auto/store/x/abc")
        self.assertEqual(i.validade, "2026-11-19T07:59:59Z")
        self.assertEqual(eshop.converter(produto_eshop(platformCode="NINTENDO_SWITCH_2")).categoria, "Switch 2")

    def test_converter_sem_desconto_e_nao_jogo(self):
        i = eshop.converter(produto_eshop(final=100, cheio=100))
        self.assertEqual((i.original_cent, i.validade), (0, ""))
        self.assertIsNone(eshop.converter(produto_eshop(topLevelCategory={"code": "MERCHANDISE"})))
        self.assertIsNone(eshop.converter(produto_eshop(prices={})))

    def test_extrai_sem_repetir(self):
        html = pagina_eshop([produto_eshop("1", "A"), produto_eshop("2", "B")])
        self.assertEqual(sorted(p["name"] for p in eshop.extrair_produtos(html)), ["A", "B"])
        with self.assertRaises(ErroDaFonte):
            eshop.extrair_produtos("<html>sem dados</html>")

    def test_fluxo_e_texto(self):
        html = pagina_eshop([produto_eshop("1", "Jogo Bom"), produto_eshop("2", "Jogo Baratinho", final=9.9, cheio=39.9),
                             produto_eshop("3", "Jogo Sem Promo", final=200, cheio=200)])
        itens = eshop.Eshop(baixar=lambda: html).coletar()
        with tempfile.TemporaryDirectory() as d:
            con = db.conectar(Path(d) / "t.db")
            r = processar(con, itens, CATALOGO, REGRAS, AGORA)
            self.assertEqual((r["recebidos"], r["reprovados_reputacao"], r["acompanhados"], r["ofertas_novas"]), (3, 1, 2, 1))
            o = db.listar_ofertas(con)
            texto = exportar.texto_do_post(o[0], REGRAS["link_grupo"])
            con.close()
        self.assertIn("🔥 *[Switch] Jogo Bom* via Nintendo eShop 🇧🇷", texto)
        self.assertIn("De ~R$ 161,20~ por *R$ 112,84* (30% off)", texto)
        self.assertIn("⏰ Até 19/11 às 04h59", texto)
        self.assertNotIn("Vendido por", texto)


class Parcelas(unittest.TestCase):
    def test_total_e_a_vista(self):
        self.assertEqual(exportar.total_parcelado("8x de R$ 55,04 sem juros"), 44032)
        self.assertEqual(exportar.total_parcelado("10x de R$ 1.234,56"), 1234560)
        self.assertEqual(exportar.total_parcelado(""), 0)
        self.assertFalse(exportar.preco_e_a_vista(43990, "8x de R$ 55,04 sem juros"))   # 440,32 ~ 439,90
        self.assertTrue(exportar.preco_e_a_vista(29440, "6x de R$ 51,65 sem juros"))    # 309,90 > 294,40
        self.assertEqual(exportar.linha_parcelas(43990, "8x de R$ 55,04 sem juros"), "💳 Em até 8x de R$ 55,04 sem juros")
        self.assertEqual(exportar.linha_parcelas(29440, "6x de R$ 51,65 sem juros"), "💳 Ou em até 6x de R$ 51,65 sem juros")
        self.assertEqual(exportar.linha_parcelas(100, ""), "")


class GitHub(unittest.TestCase):
    def test_nunca_envia_segredos_nem_banco(self):
        from robo import github
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            for rel in ["promos/.env", "promos/.env.example", "promos/robo/a.py", "promos/dados/promos.db",
                        "promos/dados/perfil_navegador/Cookies", "promos/dados/ofertas.json", "docs/index.html",
                        ".gitignore", "promos/robo/__pycache__/a.pyc", "promos/.env.local"]:
                (raiz / rel).parent.mkdir(parents=True, exist_ok=True)
                (raiz / rel).write_text("x")
            self.assertEqual(github.arquivos_do_projeto(raiz),
                             [".gitignore", "docs/index.html", "promos/.env.example", "promos/robo/a.py"])

    def test_prepara_a_pagina_uma_vez(self):
        from robo import github
        estado = {"existe": False, "pages": False, "log": []}

        def enviar(metodo, caminho, corpo):
            estado["log"].append((metodo, caminho))
            if (metodo, caminho) == ("GET", "/repos/dono/pag"):
                return (200, {}) if estado["existe"] else (404, {})
            if caminho == "/user/repos":
                estado["existe"] = True
                self.assertEqual((corpo["name"], corpo["private"]), ("pag", False))
                return 201, {}
            if caminho == "/repos/dono/pag/pages":
                if estado["pages"]:
                    return 409, {}
                estado["pages"] = True
                return 201, {}
            return 500, {}

        self.assertEqual(github.preparar_pagina("t", "dono/pag", enviar=enviar), ["repositorio criado", "GitHub Pages ligado"])
        self.assertEqual(github.preparar_pagina("t", "dono/pag", enviar=enviar), [])
        with self.assertRaises(github.ErroGitHub):
            github.preparar_pagina("t", "dono/pag", enviar=lambda m, c, b: (401, {}))
        with self.assertRaises(github.ErroGitHub) as e:     # repositorio ainda privado: avisa, nao tenta publicar
            github.preparar_pagina("t", "dono/pag", "docs", enviar=lambda m, c, b: (200, {"private": True}))
        self.assertIn("privado", str(e.exception))
        pedidos = []

        def enviar_docs(m, c, b):
            pedidos.append(b)
            return (200, {"private": False}) if m == "GET" else (201, {})

        github.preparar_pagina("t", "dono/pag", "docs", enviar=enviar_docs)
        self.assertEqual(pedidos[-1], {"source": {"branch": "main", "path": "/docs"}})

    def test_envia_so_o_que_mudou(self):
        from robo import github
        self.assertEqual(github.sha_git(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "a.py").write_text("igual")
            (raiz / "b.py").write_text("novo conteudo")
            (raiz / "c.py").write_text("arquivo novo")
            (raiz / ".env").write_text("SEGREDO=1")
            chamadas = []

            def enviar(metodo, caminho, corpo):
                chamadas.append((metodo, caminho, corpo))
                if metodo == "GET":
                    return 200, {"tree": [{"path": "a.py", "sha": github.sha_git(b"igual")}, {"path": "b.py", "sha": "velho"}]}
                return 200, {}

            r = github.enviar_codigo("t", "dono/repo", raiz, enviar=enviar)
        self.assertEqual(r, {"criado": 1, "atualizado": 1, "igual": 1})
        puts = {c[1]: c[2] for c in chamadas if c[0] == "PUT"}
        self.assertEqual(sorted(puts), ["/repos/dono/repo/contents/b.py", "/repos/dono/repo/contents/c.py"])
        self.assertEqual(puts["/repos/dono/repo/contents/b.py"]["sha"], "velho")
        self.assertNotIn("sha", puts["/repos/dono/repo/contents/c.py"])
        self.assertFalse(any(".env" in c[1] for c in chamadas))


class Painel(unittest.TestCase):
    def test_pagina_embute_os_dados_com_seguranca(self):
        dados = {"gerado_em": "2026-11-12T15:00:00Z", "total": 1,
                 "ofertas": [{"titulo": "Jogo </script><b>x", "texto": "t"}]}
        html = painel.montar(dados)
        self.assertNotIn("</script><b>x", html)
        self.assertIn("Jogo <\\/script><b>x", html)
        self.assertEqual(html.count("__DADOS__"), 0)

    def test_banco_antigo_ganha_a_coluna_nova(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            caminho = Path(d) / "velho.db"
            c = sqlite3.connect(caminho)
            c.execute("CREATE TABLE produtos (id INTEGER PRIMARY KEY, loja TEXT NOT NULL, id_loja TEXT NOT NULL, titulo TEXT, categoria TEXT, chave_produto TEXT, url TEXT, url_afiliado TEXT, imagem TEXT, vendedor TEXT, selo TEXT, nota REAL, vendas INTEGER, comissao_pct REAL, primeiro_visto TEXT, ultimo_visto TEXT, UNIQUE (loja, id_loja))")
            c.commit(); c.close()
            con = db.conectar(caminho)
            processar(con, [item(original_cent=30000)], CATALOGO, REGRAS, AGORA)
            self.assertEqual(len(db.listar_ofertas(con)), 1)
            con.close()


class AmazonSiteLocal(amazon_site.AmazonSite):
    """Mesma classe do robo, apontada para as paginas ficticias de tests/paginas."""
    arquivo_busca = "busca.html"

    def url_busca(self, palavra, pagina=1):
        return (PAGINAS / self.arquivo_busca).as_uri()

    def url_produto(self, asin):
        return (PAGINAS / f"{asin}.html").as_uri()


class AmazonPeloSite(unittest.TestCase):
    def test_converter_e_vendedor(self):
        i = amazon_site.converter({"asin": "B0X", "titulo": "Jogo", "preco": 43990, "de": 57990, "imagem": "i"}, "tag-20")
        self.assertEqual((i.id_loja, i.preco_cent, i.original_cent, i.vendedor), ("B0X", 43990, 57990, ""))
        self.assertEqual(i.url_afiliado, "https://www.amazon.com.br/dp/B0X?tag=tag-20")
        # valor "riscado" menor que o preco e parcela (12x), nao preco "de"
        self.assertEqual(amazon_site.converter({"asin": "B", "titulo": "J", "preco": 43990, "de": 5504}).original_cent, 0)
        self.assertIsNone(amazon_site.converter({"asin": "B", "titulo": "J", "preco": 0}))
        self.assertEqual(amazon_site.converter({"asin": "B", "titulo": "J", "preco": 10}).url_afiliado, "")
        self.assertEqual(amazon_site.nome_do_vendedor("Enviado / Vendido Amazon.com.br Amazon.com.br"), ("Amazon.com.br", "oficial"))
        self.assertEqual(amazon_site.nome_do_vendedor("Vendido por Loja X"), ("Loja X", ""))
        self.assertEqual(amazon_site.nome_do_vendedor("NegociuN NegociuN  NegociuN"), ("NegociuN", ""))
        self.assertEqual(amazon_site.nome_do_vendedor("Loja Boa Loja Boa"), ("Loja Boa", ""))

    @unittest.skipUnless(TEM_PLAYWRIGHT, "Playwright nao instalado")
    def test_navegador_de_verdade_em_paginas_ficticias(self):
        with tempfile.TemporaryDirectory() as d:
            nav = Navegador(Path(d) / "perfil", canais=(None, "msedge", "chrome"))
            fonte = AmazonSiteLocal({"AMAZON_PARTNER_TAG": "tag-20"}, nav, pausa=None)
            con = db.conectar(Path(d) / "t.db")
            try:
                itens = fonte.buscar("qualquer", 1)
                self.assertEqual([(i.id_loja, i.preco_cent, i.original_cent) for i in itens],
                                 [("B0AAA00001", 43990, 57990), ("B0AAA00002", 129900, 0),
                                  ("B0AAA00003", 20000, 40000), ("B0AAA00004", 5000, 0)])
                r = processar(con, itens, CATALOGO, REGRAS, AGORA, verificador=fonte.verificar)
                # 4 lidos; o cabo fica fora do catalogo; 3 acompanhados; 2 com sinal sao conferidos
                # na pagina do produto: um e vendido pela Amazon (vira oferta), o outro e de terceiro.
                self.assertEqual(r, {"recebidos": 4, "fora_do_catalogo": 1, "reprovados_reputacao": 1,
                                     "acompanhados": 3, "ofertas_novas": 1, "verificados": 2})
                o = db.listar_ofertas(con)[0]
                self.assertEqual((o["titulo"], o["vendedor"], o["selo"]), ("Jogo Ficticio Um - Nintendo Switch 2", "Amazon.com.br", "oficial"))
                self.assertEqual(o["preco_cent"], 42990)         # preco confirmado na pagina do produto
                texto = exportar.texto_do_post(o, REGRAS["link_grupo"])
                # 8 x 55,04 = 440,32, acima de 429,90: o preco mostrado e o a vista
                self.assertIn("De ~R$ 579,90~ por *R$ 429,90* à vista (26% off)", texto)
                self.assertIn("💳 Ou em até 8x de R$ 55,04 sem juros", texto)
                self.assertEqual(o["url_afiliado"], "https://www.amazon.com.br/dp/B0AAA00001?tag=tag-20")
                # ciclo seguinte: vendedor ja conhecido, nada e conferido de novo; o terceiro segue barrado
                r2 = processar(con, fonte.buscar("qualquer", 1), CATALOGO, REGRAS, AGORA + timedelta(hours=1), verificador=fonte.verificar)
                self.assertEqual((r2["verificados"], r2["ofertas_novas"], r2["reprovados_reputacao"]), (0, 0, 1))
                # CAPTCHA: para e nao tenta de novo no mesmo ciclo
                fonte.arquivo_busca = "captcha.html"
                with self.assertRaises(ErroDaFonte):
                    fonte.buscar("qualquer", 1)
                self.assertTrue(fonte.bloqueada)
                fonte.arquivo_busca = "busca.html"
                with self.assertRaises(ErroDaFonte):
                    fonte.buscar("qualquer", 1)
            finally:
                con.close()
                fonte.fechar()

    def test_limite_de_verificacoes_por_ciclo(self):
        chamadas = []

        def verificador(i):
            chamadas.append(i.id_loja)
            n = Item(**i.__dict__)
            n.vendedor, n.selo = "Amazon.com.br", "oficial"
            return n

        with tempfile.TemporaryDirectory() as d:
            con = db.conectar(Path(d) / "t.db")
            itens = [item(loja="amazon", id_loja=f"A{k}", original_cent=30000, selo="", vendedor="") for k in range(5)]
            r = processar(con, itens, CATALOGO, REGRAS, AGORA, verificador=verificador, max_verificacoes=2)
            con.close()
        self.assertEqual((len(chamadas), r["ofertas_novas"], r["acompanhados"]), (2, 2, 5))


class MercadoLivreLocal(mercadolivre_site.MercadoLivreSite):
    def url_busca(self, palavra, pagina=1):
        return (PAGINAS / "ml_busca.html").as_uri()


class MercadoLivrePeloSite(unittest.TestCase):
    def test_converter(self):
        i = mercadolivre_site.converter({"titulo": "Jogo", "url": "https://produto.mercadolivre.com.br/MLB-123-jogo-_JM#x=1",
                                         "preco": 35991, "de": 44990, "vendedor": "Por Loja X", "oficial": True})
        self.assertEqual((i.id_loja, i.url, i.vendedor, i.selo, i.url_afiliado),
                         ("MLB123", "https://produto.mercadolivre.com.br/MLB-123-jogo-_JM", "Loja X", "oficial", ""))
        self.assertIsNone(mercadolivre_site.converter({"titulo": "x", "url": "https://example.com/a", "preco": 10}))

    @unittest.skipUnless(TEM_PLAYWRIGHT, "Playwright nao instalado")
    def test_navegador_de_verdade_em_pagina_ficticia(self):
        with tempfile.TemporaryDirectory() as d:
            fonte = MercadoLivreLocal({}, Navegador(Path(d) / "perfil", canais=(None, "msedge", "chrome")), pausa=None)
            con = db.conectar(Path(d) / "t.db")
            try:
                bruto = fonte.buscar_bruto("x")
                self.assertEqual((len(bruto["itens"]), len(bruto["amostra_html"]), bruto["login"]), (3, 2, False))
                itens = fonte.buscar("x")
                self.assertEqual([(i.id_loja, i.preco_cent, i.original_cent, i.selo, i.vendedor) for i in itens],
                                 [("MLB1234567890", 35991, 44990, "oficial", "Loja Ficticia"),
                                  ("MLB44556677", 129900, 0, "", "Vendedor Comum")])
                self.assertEqual((itens[0].nota, itens[0].vendas), (4.8, 1532))
                self.assertEqual(itens[0].parcelas, "10x de R$ 35,99 sem juros")
                r = processar(con, itens, CATALOGO, REGRAS, AGORA)
                self.assertEqual((r["acompanhados"], r["reprovados_reputacao"], r["ofertas_novas"]), (1, 1, 1))
                self.assertFalse(db.listar_ofertas(con)[0]["url_afiliado"])
            finally:
                con.close()
                fonte.fechar()


class Fluxo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def amostra(self):
        return [shopee.converter(n) for n in AMOSTRA["data"]["productOfferV2"]["nodes"]]

    def test_amostra_completa(self):
        r = processar(self.con, self.amostra(), CATALOGO, REGRAS, AGORA)
        self.assertEqual(r, {"recebidos": 7, "fora_do_catalogo": 2, "reprovados_reputacao": 1,
                             "acompanhados": 4, "ofertas_novas": 2, "verificados": 0})
        titulos = [o["titulo"] for o in db.listar_ofertas(self.con)]
        self.assertEqual(len(titulos), 2)
        self.assertTrue(titulos[0].startswith("LEGO"))          # 33% vem antes de 22%
        self.assertFalse(any("Pelicula" in t for t in titulos))  # abaixo do preco minimo

    def test_nao_repete_a_mesma_oferta(self):
        processar(self.con, self.amostra(), CATALOGO, REGRAS, AGORA)
        r = processar(self.con, self.amostra(), CATALOGO, REGRAS, AGORA + timedelta(minutes=30))
        self.assertEqual(r["ofertas_novas"], 0)

    def test_repete_se_cair_mais(self):
        processar(self.con, [item(preco_cent=20000, original_cent=30000)], CATALOGO, REGRAS, AGORA)
        r = processar(self.con, [item(preco_cent=19900, original_cent=30000)], CATALOGO, REGRAS, AGORA + timedelta(hours=1))
        self.assertEqual(r["ofertas_novas"], 0)                 # queda de 0,5%: ignora
        r = processar(self.con, [item(preco_cent=18000, original_cent=30000)], CATALOGO, REGRAS, AGORA + timedelta(hours=2))
        self.assertEqual(r["ofertas_novas"], 1)

    def test_repete_depois_do_prazo(self):
        processar(self.con, [item(preco_cent=20000, original_cent=30000)], CATALOGO, REGRAS, AGORA)
        r = processar(self.con, [item(preco_cent=20000, original_cent=30000)], CATALOGO, REGRAS, AGORA + timedelta(hours=49))
        self.assertEqual(r["ofertas_novas"], 1)

    def test_item_duplicado_na_mesma_coleta(self):
        r = processar(self.con, [item(), item()], CATALOGO, REGRAS, AGORA)
        self.assertEqual(r["recebidos"], 1)

    def test_historico_grava_mudanca_e_ignora_repeticao(self):
        for minutos, preco in [(0, 20000), (30, 20000), (60, 19000), (60 + 7 * 60, 19000)]:
            processar(self.con, [item(preco_cent=preco)], CATALOGO, REGRAS, AGORA + timedelta(minutes=minutos))
        precos = [l[0] for l in self.con.execute("SELECT preco_cent FROM precos ORDER BY coletado_em")]
        self.assertEqual(precos, [20000, 19000, 19000])         # repetido so apos 6h

    def test_sinal_de_historico_com_dados_acumulados(self):
        for d in range(8, 0, -1):
            processar(self.con, [item(preco_cent=20000)], CATALOGO, REGRAS, AGORA - timedelta(days=d))
        self.assertEqual(db.listar_ofertas(self.con), [])
        processar(self.con, [item(preco_cent=16000)], CATALOGO, REGRAS, AGORA)
        o = db.listar_ofertas(self.con)[0]
        s = json.loads(o["sinais"])[0]
        self.assertEqual((s["tipo"], s["pct"]), ("historico", 20.0))
        self.assertIn("menor preco em 8 dias", s["texto"])

    def test_entre_lojas_com_produto_cadastrado(self):
        c = dict(CATALOGO, produtos=[{"chave": "jt", "termos": ["jogo teste"], "preco_sugerido_reais": 0}])
        processar(self.con, [item(loja="amazon", id_loja="A", preco_cent=30000)], c, REGRAS, AGORA)
        processar(self.con, [item(loja="shopee", id_loja="S", preco_cent=25000)], c, REGRAS, AGORA + timedelta(minutes=5))
        o = db.listar_ofertas(self.con)
        self.assertEqual(len(o), 1)
        self.assertEqual((o[0]["loja"], json.loads(o[0]["sinais"])[0]["tipo"]), ("shopee", "entre_lojas"))

    def test_texto_e_json(self):
        processar(self.con, [item(titulo="Sonic X Shadow Generations Nintendo Switch 2", preco_cent=17517,
                                  original_cent=22738, vendedor="Amazon", url_afiliado="https://example.com/af")],
                  CATALOGO, REGRAS, AGORA)
        o = db.listar_ofertas(self.con)
        texto = exportar.texto_do_post(o[0], REGRAS["link_grupo"])
        self.assertIn("🔥 *[Switch 2] Sonic X Shadow Generations Nintendo Switch 2* via Shopee 🇧🇷", texto)
        self.assertIn("De ~R$ 227,38~ por *R$ 175,17* (23% off)", texto)
        self.assertIn("👉 https://example.com/af", texto)
        self.assertIn("https://projectn.com.br/promo", texto)
        caminho = Path(self.tmp.name) / "ofertas.json"
        exportar.gravar_json(o, caminho, REGRAS["link_grupo"], "2026-11-12T15:00:00Z")
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertEqual((dados["total"], dados["ofertas"][0]["preco"], dados["ofertas"][0]["tem_link_afiliado"]),
                         (1, 175.17, True))


class Env(unittest.TestCase):
    def test_le_env(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('# comentario\nSHOPEE_APP_ID=123\nSHOPEE_SECRET="abc=def"\n\nlixo\n', encoding="utf-8")
            env = config.carregar_env(p)
            self.assertEqual((env["SHOPEE_APP_ID"], env["SHOPEE_SECRET"]), ("123", "abc=def"))


if __name__ == "__main__":
    unittest.main()
