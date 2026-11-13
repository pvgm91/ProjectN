"""Gera o texto do post e o arquivo ofertas.json que o painel vai ler."""
import json
import re
from datetime import datetime, timedelta

NOMES_LOJA = {"eshop": "Nintendo eShop", "shopee": "Shopee", "amazon": "Amazon", "mercadolivre": "Mercado Livre", "manual": "loja"}


def reais(centavos):
    inteiro, cent = divmod(int(centavos), 100)
    return "R$ " + f"{inteiro:,}".replace(",", ".") + f",{cent:02d}"


def linha_validade(validade_utc):
    """'2026-11-19T07:59:59Z' -> '⏰ Até 19/11 às 04h59' (horario de Brasilia)."""
    if not validade_utc:
        return ""
    try:
        fim = datetime.strptime(validade_utc[:19], "%Y-%m-%dT%H:%M:%S") - timedelta(hours=3)
    except ValueError:
        return ""
    return f"⏰ Até {fim:%d/%m} às {fim:%Hh%M}"


PARCELA = re.compile(r"(\d{1,2})x de R\$ ([\d.]+,\d{2})")


def total_parcelado(parcelas):
    """'6x de R$ 51,65 sem juros' -> 30990 (centavos). 0 se nao der para ler."""
    m = PARCELA.search(parcelas or "")
    if not m:
        return 0
    return int(m.group(1)) * int(round(float(m.group(2).replace(".", "").replace(",", ".")) * 100))


def preco_e_a_vista(preco_cent, parcelas):
    """True quando o parcelado soma mais de 1% acima do preco: o preco mostrado e o a vista (Pix)."""
    total = total_parcelado(parcelas)
    return bool(total) and total > preco_cent * 1.01


def linha_parcelas(preco_cent, parcelas):
    if not parcelas:
        return ""
    return ("💳 Ou em até " if preco_e_a_vista(preco_cent, parcelas) else "💳 Em até ") + parcelas


def texto_do_post(o, link_grupo):
    """Texto no padrao do grupo, com a formatacao do WhatsApp (*negrito*, ~riscado~)."""
    sinais = json.loads(o["sinais"])
    loja = NOMES_LOJA.get(o["loja"], o["loja"])
    linhas = [f"🔥 *[{o['categoria']}] {o['titulo']}* via {loja} 🇧🇷"]
    a_vista = " à vista" if preco_e_a_vista(o["preco_cent"], o["parcelas"]) else ""
    if o["referencia_cent"] and sinais[0]["tipo"] == "desconto_loja":
        linhas.append(f"De ~{reais(o['referencia_cent'])}~ por *{reais(o['preco_cent'])}*{a_vista} ({o['desconto_pct']:.0f}% off)")
    else:
        linhas.append(f"Por *{reais(o['preco_cent'])}*{a_vista} ({sinais[0]['texto']})")
    if linha_parcelas(o["preco_cent"], o["parcelas"]):
        linhas.append(linha_parcelas(o["preco_cent"], o["parcelas"]))
    if linha_validade(o["validade"]):
        linhas.append(linha_validade(o["validade"]))
    if o["vendedor"] and o["loja"] != "eshop":
        selo = {"oficial": " (loja oficial)", "indicada": " (loja indicada)"}.get(o["selo"], "")
        linhas.append(f"📦 Vendido por {o['vendedor']}{selo}")
    linhas += ["", f"👉 {o['url_afiliado'] or o['url']}", "",
               f"📢 Entre no grupo de promoções do Project N:\n{link_grupo}"]
    return "\n".join(linhas)


def oferta_para_dict(o, link_grupo):
    return {
        "id": o["id"], "detectada_em": o["detectada_em"], "status": o["status"],
        "loja": o["loja"], "categoria": o["categoria"], "titulo": o["titulo"],
        "preco": o["preco_cent"] / 100, "referencia": (o["referencia_cent"] or 0) / 100,
        "desconto_pct": o["desconto_pct"], "sinais": json.loads(o["sinais"]),
        "vendedor": o["vendedor"], "selo": o["selo"], "nota": o["nota"], "vendas": o["vendas"],
        "comissao_pct": o["comissao_pct"], "imagem": o["imagem"],
        "url": o["url"], "url_afiliado": o["url_afiliado"],
        "tem_link_afiliado": bool(o["url_afiliado"]),
        "parcelas": o["parcelas"] or "", "linha_parcelas": linha_parcelas(o["preco_cent"], o["parcelas"]),
        "a_vista": preco_e_a_vista(o["preco_cent"], o["parcelas"]),
        "validade": o["validade"] or "", "linha_validade": linha_validade(o["validade"]),
        "texto": texto_do_post(o, link_grupo),
    }


def gravar_json(ofertas, caminho, link_grupo, gerado_em):
    dados = {"gerado_em": gerado_em, "total": len(ofertas),
             "ofertas": [oferta_para_dict(o, link_grupo) for o in ofertas]}
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    return dados
