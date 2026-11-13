"""Formato unico de item, igual para todas as lojas."""
from dataclasses import dataclass


class SemCredenciais(Exception):
    """A loja ainda nao tem chave configurada no .env."""


class ErroDaFonte(Exception):
    """A API da loja respondeu com erro."""


@dataclass
class Item:
    loja: str                 # shopee | amazon | mercadolivre | manual
    id_loja: str              # identificador do anuncio na loja
    titulo: str
    preco_cent: int           # preco atual, em centavos
    original_cent: int = 0    # preco "de" informado pela loja (0 = nao informado)
    url: str = ""
    url_afiliado: str = ""
    imagem: str = ""
    vendedor: str = ""
    selo: str = ""            # oficial | indicada | "" (sem selo)
    nota: float = 0.0
    vendas: int = 0
    comissao_pct: float = 0.0
    categoria: str = ""       # preenchida pela fonte quando ela ja sabe (ex.: eShop); senao vem do catalogo
    parcelas: str = ""        # ex.: '8x de R$ 55,04 sem juros', como a loja mostra
    validade: str = ""        # fim da promocao, em UTC (ISO), quando a loja informa


def para_centavos(valor):
    """'175.17', '175,17', 'R$ 1.234,56' ou 175.17 -> centavos (int)."""
    if valor is None or valor == "":
        return 0
    if isinstance(valor, (int, float)):
        return int(round(float(valor) * 100))
    s = str(valor).replace("R$", "").strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return 0
