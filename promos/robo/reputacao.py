"""Filtro de vendedor: so passa quem cumpre os limites de regras.json."""


def aprovado(item, regras):
    """Devolve (True, '') ou (False, motivo)."""
    r = regras.get("reputacao", {}).get(item.loja, {})
    if r.get("exigir_selo") and not item.selo:
        return False, "vendedor sem selo (loja oficial ou indicada)"
    nota_min = r.get("nota_minima", 0)
    if nota_min and item.nota < nota_min:
        return False, f"nota {item.nota:.1f} abaixo de {nota_min}"
    vendas_min = r.get("vendas_minimas", 0)
    if item.vendas < vendas_min:
        return False, f"{item.vendas} vendas, minimo {vendas_min}"
    cheio_min = r.get("preco_cheio_minimo_reais", 0) * 100
    if cheio_min and max(item.original_cent, item.preco_cent) < cheio_min:
        return False, f"preco cheio abaixo de R$ {cheio_min // 100}"
    return True, ""
