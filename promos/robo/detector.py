"""Regras que transformam um preco em oferta. Funcoes puras: sem banco, sem rede.

Cada sinal devolve {"tipo", "pct", "referencia_cent", "texto"}.
pct = quanto o preco atual esta abaixo da referencia usada pelo sinal.
"""
from statistics import median


def _pct_abaixo(preco, referencia):
    if not referencia or referencia <= 0 or preco >= referencia:
        return 0.0
    return round((referencia - preco) / referencia * 100, 1)


def sinal_desconto_loja(preco, original, regras):
    """Sinal 1 (dia 1): o 'de/por' informado pela propria loja."""
    pct = _pct_abaixo(preco, original)
    if pct >= regras["sinais"]["desconto_loja_min_pct"]:
        return {"tipo": "desconto_loja", "pct": pct, "referencia_cent": original,
                "texto": f"{pct:.0f}% abaixo do preco 'de' da loja"}
    return None


def sinal_preco_sugerido(preco, sugerido, regras):
    """Sinal 2 (dia 1): abaixo do preco cheio cadastrado em catalogo.json."""
    pct = _pct_abaixo(preco, sugerido)
    if pct >= regras["sinais"]["abaixo_do_sugerido_min_pct"]:
        return {"tipo": "preco_sugerido", "pct": pct, "referencia_cent": sugerido,
                "texto": f"{pct:.0f}% abaixo do preco sugerido"}
    return None


def sinal_entre_lojas(preco, precos_outras_lojas, regras):
    """Sinal 3 (dia 1): mesmo produto mais caro nas outras lojas."""
    if not precos_outras_lojas:
        return None
    referencia = int(median(precos_outras_lojas))
    pct = _pct_abaixo(preco, referencia)
    if pct >= regras["sinais"]["entre_lojas_min_pct"]:
        return {"tipo": "entre_lojas", "pct": pct, "referencia_cent": referencia,
                "texto": f"{pct:.0f}% abaixo das outras lojas"}
    return None


def sinal_historico(preco, minimos_diarios, regras):
    """Sinal 4 (apos alguns dias): abaixo da mediana do proprio historico.

    minimos_diarios: menor preco de cada dia anterior, um valor por dia.
    """
    dias = len(minimos_diarios)
    if dias < regras["sinais"]["historico_min_dias"]:
        return None
    referencia = int(median(minimos_diarios))
    pct = _pct_abaixo(preco, referencia)
    if pct < regras["sinais"]["historico_min_pct"]:
        return None
    texto = f"{pct:.0f}% abaixo da mediana de {dias} dias"
    if preco <= min(minimos_diarios):
        texto = f"menor preco em {dias} dias ({pct:.0f}% abaixo da mediana)"
    return {"tipo": "historico", "pct": pct, "referencia_cent": referencia, "texto": texto}


def detectar(preco, original, sugerido, precos_outras_lojas, minimos_diarios, regras):
    """Aplica os quatro sinais e devolve os que dispararam, do mais forte ao mais fraco."""
    if preco < regras.get("preco_minimo_reais", 0) * 100:
        return []
    sinais = [
        sinal_desconto_loja(preco, original, regras),
        sinal_preco_sugerido(preco, sugerido, regras),
        sinal_entre_lojas(preco, precos_outras_lojas, regras),
        sinal_historico(preco, minimos_diarios, regras),
    ]
    return sorted([s for s in sinais if s], key=lambda s: -s["pct"])
