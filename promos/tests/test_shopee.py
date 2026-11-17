"""Testes do conector da Shopee (Open API de afiliados), sem rede.

Rodar, dentro da pasta promos:  py -3 -m unittest tests.test_shopee -v
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from robo.fontes.base import ErroDaFonte, SemCredenciais        # noqa: E402
from robo.fontes.shopee import Shopee, assinar, converter, montar_consulta      # noqa: E402

ENV = {"SHOPEE_APP_ID": "18012345678", "SHOPEE_SECRET": "SEGREDO"}


def no(**extra):
    base = {"itemId": 123, "productName": "Mario Kart World - Nintendo Switch 2", "priceMin": "299.90",
            "priceMax": "299.90", "price": "299.90", "sales": 812, "ratingStar": "4.9", "priceDiscountRate": 25,
            "imageUrl": "https://img", "shopId": 9, "shopName": "Loja Oficial", "shopType": [1],
            "productLink": "https://shopee.com.br/p/123", "offerLink": "https://s.shopee.com.br/abc",
            "commissionRate": "0.08"}
    base.update(extra)
    return base


def resposta(nodes, tem_mais=False):
    return {"data": {"productOfferV2": {"nodes": nodes, "pageInfo": {"page": 1, "limit": 50, "hasNextPage": tem_mais}}}}


class Falso:
    """Faz o papel da Shopee: devolve as respostas da fila e guarda o que recebeu."""

    def __init__(self, *respostas):
        self.respostas, self.pedidos = list(respostas), []

    def __call__(self, corpo, cabecalhos):
        self.pedidos.append((corpo, cabecalhos))
        return self.respostas.pop(0)


class TestShopee(unittest.TestCase):
    def test_assinatura_segue_a_regra_da_shopee(self):
        esperado = hashlib.sha256(b"APP1700000000{\"query\":\"x\"}SEG").hexdigest()
        self.assertEqual(assinar("APP", "SEG", '{"query":"x"}', 1700000000),
                         f"SHA256 Credential=APP, Timestamp=1700000000, Signature={esperado}")

    def test_assina_exatamente_o_corpo_enviado(self):
        falso = Falso(resposta([no()]))
        Shopee(ENV, enviar=falso, dormir=lambda s: None).buscar("mario kart", 1)
        corpo, cab = falso.pedidos[0]
        ts = cab["Authorization"].split("Timestamp=")[1].split(",")[0]
        self.assertEqual(cab["Authorization"], assinar(ENV["SHOPEE_APP_ID"], ENV["SHOPEE_SECRET"], corpo, int(ts)))
        self.assertIn("productOfferV2", json.loads(corpo)["query"])

    def test_converte_preco_de_selo_e_comissao(self):
        i = converter(no())
        self.assertEqual((i.preco_cent, i.original_cent), (29990, 39987))      # 299,90 com 25% de desconto
        self.assertEqual((i.selo, i.vendas, i.nota, i.comissao_pct), ("oficial", 812, 4.9, 8.0))
        self.assertEqual(i.url_afiliado, "https://s.shopee.com.br/abc")
        self.assertEqual(converter(no(shopType=[2])).selo, "indicada")
        self.assertEqual(converter(no(shopType=[])).selo, "")
        self.assertIsNone(converter(no(priceMin=None, price=None)))

    def test_consulta_escapa_aspas_da_busca(self):
        self.assertIn('keyword: "Zelda \\"TOTK\\""', montar_consulta('Zelda "TOTK"', 1, 10))

    def test_sem_chave_pula_a_loja(self):
        with self.assertRaises(SemCredenciais):
            Shopee({"SHOPEE_APP_ID": "  ", "SHOPEE_SECRET": ""})

    def test_chave_com_espaco_sobrando_no_env(self):
        s = Shopee({"SHOPEE_APP_ID": " 180 ", "SHOPEE_SECRET": "abc \n"}, enviar=Falso())
        self.assertEqual((s.app_id, s.secret), ("180", "abc"))

    def test_segue_as_paginas_ate_acabar(self):
        falso = Falso(resposta([no(itemId=1)], True), resposta([no(itemId=2)], False))
        itens = Shopee(ENV, enviar=falso, dormir=lambda s: None).buscar("switch 2", paginas=5)
        self.assertEqual([i.id_loja for i in itens], ["1", "2"])
        self.assertEqual(len(falso.pedidos), 2)

    def test_limite_de_chamadas_espera_e_tenta_de_novo(self):
        limite = {"errors": [{"message": "rate limit", "extensions": {"code": 10030}}]}
        esperas = []
        falso = Falso(limite, resposta([no()]))
        itens = Shopee(ENV, enviar=falso, dormir=esperas.append).buscar("switch", 1)
        self.assertEqual(len(itens), 1)
        self.assertEqual(esperas, [5])

    def test_erro_de_assinatura_para_a_loja_e_explica(self):
        erro = {"errors": [{"message": "Invalid Signature", "extensions": {"code": 10020}}]}
        s = Shopee(ENV, enviar=Falso(erro), dormir=lambda s: None)
        with self.assertRaises(ErroDaFonte) as ctx:
            s.buscar("switch", 1)
        self.assertTrue(s.bloqueada)
        texto = str(ctx.exception)
        self.assertIn("SHOPEE_SECRET", texto)
        for palavra in ("credenciais", "expirou", "recusou"):       # nao pode sugerir 'rodar.bat entrar shopee'
            self.assertNotIn(palavra, texto.lower())

    def test_erro_do_sistema_tenta_de_novo(self):
        sistema = {"errors": [{"message": "System Error", "extensions": {"code": 10000}}]}
        esperas = []
        itens = Shopee(ENV, enviar=Falso(sistema, resposta([no()])), dormir=esperas.append).buscar("switch", 1)
        self.assertEqual((len(itens), esperas), (1, [3]))

    def test_erro_do_sistema_persistente_vira_erro(self):
        sistema = {"errors": [{"message": "System Error", "extensions": {"code": 10000}}]}
        s = Shopee(ENV, enviar=Falso(sistema, sistema, sistema, sistema), dormir=lambda s: None)
        with self.assertRaises(ErroDaFonte):
            s.buscar("switch", 1)
        self.assertFalse(s.bloqueada)

    def test_outro_erro_nao_bloqueia_a_loja(self):
        erro = {"errors": [{"message": "business error", "extensions": {"code": 11000}}]}
        s = Shopee(ENV, enviar=Falso(erro), dormir=lambda s: None)
        with self.assertRaises(ErroDaFonte):
            s.buscar("switch", 1)
        self.assertFalse(s.bloqueada)


if __name__ == "__main__":
    unittest.main()
