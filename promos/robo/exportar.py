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


PATROCINADO = re.compile(r"^\s*(an[uú]ncio\s+patrocinado|patrocinado)\s*[-–—:]?\s*", re.I)


# Tipo de produto para o menu lateral do painel. A ordem importa: a primeira regra que bate vale.
TIPOS = [
    ("Pelúcias", None, r"pel[uú]cia|plush"),
    ("Funko", "Funko", r"funko"),
    ("amiibo", "amiibo", r"\bamiibo"),
    ("LEGO", "LEGO", r"\blego\b"),
    ("Cartas Pokémon", "Cartas Pokémon", r"\b(tcg|booster|cartas|cards|elite trainer|treinador avan[cç]ado|deck (de batalha|pok[eé]mon))\b"),
    ("Livros e mangás", "Livros", r"\b(livro|mang[aá]|guia|artbook|art of|volume|vol\.)"),
    ("Consoles", None, r"^(consola|console|bundle console|nintendo switch (2|oled|lite)\b|nintendo, videogame)"),
    ("Acessórios", "Acessorios", r"\b(case|capa|bolsa|pel[ií]cula|cart[aã]o|microsd|carregador|dock|suporte|fone|headset|grip|protetor|estojo|adaptador|ssd|hd externo|mochila|bateria|kit)\b"),
    ("Controles", None, r"\b(controle|controller|joystick|joy-?con|gamepad|arcade stick|volante)"),
    ("Consoles", None, r"\bconsole\b|\bswitch oled\b|\bswitch lite\b"),
    ("Action figures", "Action figures", r"\b(action figure|figura|figure|boneco|est[aá]tua|figuarts|nendoroid|figma)\b"),
    ("Jogos", None, r"\b(jogo|game|m[ií]dia f[ií]sica|f[ií]sico|edition|edi[cç][aã]o|switch|3ds|nintendo ds|nintendo 64|wii)\b"),
]


def tipo_do_produto(titulo, categoria=""):
    """'Funko Pop Pikachu' -> 'Funko'; 'Jogo Zelda Switch' -> 'Jogos'. Usado so para filtrar no painel."""
    t = (titulo or "").lower()
    for nome, cat, regra in TIPOS:
        if re.search(regra, t):
            return nome
    for nome, cat, _ in TIPOS:      # titulo sem pista: usa a categoria do catalogo
        if cat and cat == categoria:
            return nome
    return "Outros"


IMPORTADO_NO_TITULO = re.compile(r"importad|vers[aã]o (americana|norte-americana|europeia|japonesa)|\b(usa|eua)\b|\(us\)|\bimport\b|"
                                 r"\b(us|non-us|can|eu|uk|jp|japanese|asia|asian|euro|pal) version\b|region free", re.I)
LINHA_IMPORTADO = "✈️ Produto importado, com envio internacional"


def e_importado(marca, titulo):
    return bool(marca) or bool(IMPORTADO_NO_TITULO.search(titulo or ""))


def limpar_titulo(titulo):
    return PATROCINADO.sub("", titulo or "").strip()


def texto_do_post(o, link_grupo, link=""):
    """Texto no padrao do grupo, com a formatacao do WhatsApp (*negrito*, ~riscado~)."""
    sinais = json.loads(o["sinais"])
    loja = NOMES_LOJA.get(o["loja"], o["loja"])
    linhas = [f"🔥 *[{o['categoria']}] {limpar_titulo(o['titulo'])}* via {loja} 🇧🇷"]
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
        selo = {"oficial": " (loja oficial)", "indicada": " (loja indicada)", "amazon": " (entregue pela Amazon)"}.get(o["selo"], "")
        linhas.append(f"📦 Vendido por {o['vendedor']}{selo}")
    if e_importado(o["importado"] if "importado" in o.keys() else "", o["titulo"]):
        linhas.append(LINHA_IMPORTADO)
    linhas += ["", f"👉 {link or o['url_afiliado'] or o['url']}", "",
               f"📢 Entre no grupo de promoções do Project N:\n{link_grupo}"]
    return "\n".join(linhas)


def oferta_para_dict(o, link_grupo, links=None):
    link = (links or {}).get((o["loja"], o["id_loja"]), "") if "id_loja" in o.keys() else ""
    return {
        "id": o["id"], "produto": o["produto_id"], "detectada_em": o["detectada_em"], "status": o["status"],
        "loja": o["loja"], "categoria": o["categoria"], "titulo": limpar_titulo(o["titulo"]),
        "preco": o["preco_cent"] / 100, "referencia": (o["referencia_cent"] or 0) / 100,
        "desconto_pct": o["desconto_pct"], "sinais": json.loads(o["sinais"]),
        "vendedor": o["vendedor"], "selo": o["selo"], "nota": o["nota"], "vendas": o["vendas"],
        "comissao_pct": o["comissao_pct"], "imagem": o["imagem"],
        "url": o["url"], "url_afiliado": o["url_afiliado"],
        "tem_link_afiliado": bool(o["url_afiliado"]),
        "parcelas": o["parcelas"] or "", "linha_parcelas": linha_parcelas(o["preco_cent"], o["parcelas"]),
        "a_vista": preco_e_a_vista(o["preco_cent"], o["parcelas"]),
        "validade": o["validade"] or "", "linha_validade": linha_validade(o["validade"]),
        "link_curto": link,
        "importado": e_importado(o["importado"] if "importado" in o.keys() else "", o["titulo"]),
        "texto": texto_do_post(o, link_grupo, link),
    }


def gravar_json(ofertas, caminho, link_grupo, gerado_em, links=None):
    dados = {"gerado_em": gerado_em, "total": len(ofertas),
             "ofertas": [oferta_para_dict(o, link_grupo, links) for o in ofertas]}
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    return dados


# ---------------------------------------------------------------- painel: produtos e historico

DIAS_DETALHADOS = 30      # ate 30 dias atras o grafico guarda cada mudanca; antes disso, o menor preco do dia
FOLGA_ATIVO_HORAS = 3     # produto "ativo" = visto na ultima coleta da loja, com esta folga
DIAS_NOVIDADE = 7         # "novo no radar" = apareceu nos ultimos 7 dias
CARENCIA_NOVIDADE_H = 24  # o que apareceu nas primeiras 24h de uma loja e a carga inicial, nao novidade


def _minutos(iso):
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").timestamp() // 60) if iso else 0


def pontos_do_historico(registros, agora_min):
    """registros: [(minutos_unix, preco_cent)] em ordem. Devolve [[minutos, preco], ...] para o grafico.

    - Sem repeticoes seguidas: um ponto so quando o preco muda.
    - Mais antigo que DIAS_DETALHADOS: um ponto por dia, o menor preco daquele dia.
    """
    corte = agora_min - DIAS_DETALHADOS * 1440
    antigos, recentes = {}, []
    for t, p in registros:
        if t < corte:
            dia = t // 1440
            if dia not in antigos or p < antigos[dia][1]:
                antigos[dia] = [dia * 1440 + 720, p]
        else:
            recentes.append([t, p])
    pontos = []
    for t, p in [antigos[d] for d in sorted(antigos)] + recentes:
        if not pontos or pontos[-1][1] != p:
            pontos.append([t, p])
    return pontos


def produtos_para_painel(con, agora):
    """Todos os produtos acompanhados, com preco atual, faixa historica e pontos do grafico."""
    from statistics import median
    agora_min = _minutos(agora.strftime("%Y-%m-%dT%H:%M:%SZ"))
    ultima_coleta = {l["loja"]: _minutos(l["u"]) for l in
                     con.execute("SELECT loja, MAX(ultimo_visto) AS u FROM produtos GROUP BY loja")}
    primeira_coleta = {l["loja"]: _minutos(l["p"]) for l in
                       con.execute("SELECT loja, MIN(primeiro_visto) AS p FROM produtos GROUP BY loja")}
    regs = {}
    for l in con.execute("SELECT produto_id, coletado_em, preco_cent, original_cent FROM precos ORDER BY produto_id, coletado_em"):
        regs.setdefault(l["produto_id"], []).append((_minutos(l["coletado_em"]), l["preco_cent"], l["original_cent"]))
    saida = []
    for p in con.execute("SELECT * FROM produtos WHERE COALESCE(removido, '') = ''"):
        r = regs.get(p["id"])
        if not r:
            continue
        atual, de = r[-1][1], r[-1][2]
        precos = [x[1] for x in r]
        minimos_dia = {}
        for t, preco, _ in r:
            dia = t // 1440
            minimos_dia[dia] = min(preco, minimos_dia.get(dia, preco))
        mediana = int(median(minimos_dia.values()))
        visto = _minutos(p["ultimo_visto"])
        saida.append({
            "k": p["id"], "loja": p["loja"], "id_loja": p["id_loja"], "titulo": limpar_titulo(p["titulo"]), "categoria": p["categoria"] or "",
            "tipo": tipo_do_produto(p["titulo"], p["categoria"] or ""),
            "importado": e_importado(p["importado"] if "importado" in p.keys() else "", p["titulo"]),
            "imagem": p["imagem"] or "", "url": p["url_afiliado"] or p["url"] or "",
            "tem_link_afiliado": bool(p["url_afiliado"]),
            "vendedor": p["vendedor"] or "", "selo": p["selo"] or "", "parcelas": p["parcelas"] or "",
            "atual": atual, "de": de if de > atual else 0,
            "menor": min(precos), "maior": max(precos), "mediana": mediana,
            "desde": _minutos(p["primeiro_visto"]), "visto": visto,
            "dias": len(minimos_dia), "registros": len(r),
            "ativo": visto >= ultima_coleta.get(p["loja"], 0) - FOLGA_ATIVO_HORAS * 60,
            "pontos": pontos_do_historico([(t, preco) for t, preco, _ in r], agora_min),
            "prevenda": (p["prevenda"] if "prevenda" in p.keys() else "") or "",
            "novo": _minutos(p["primeiro_visto"]) >= max(primeira_coleta.get(p["loja"], 0) + CARENCIA_NOVIDADE_H * 60,
                                                         agora_min - DIAS_NOVIDADE * 1440),
        })
    return saida


def dados_do_painel(ofertas_json, produtos, link_grupo, cupons=None, bot=""):
    """Junta ofertas e produtos. Marca se cada oferta ainda vale pelo preco mais recente."""
    por_id = {p["k"]: p for p in produtos}
    ofertas = []
    for o in ofertas_json["ofertas"]:
        p = por_id.get(o.get("produto"))
        o = dict(o)
        if p:
            preco = int(round(o["preco"] * 100))
            o["preco_atual"] = p["atual"] / 100
            o["situacao"] = ("sumiu" if not p["ativo"] else
                             "subiu" if p["atual"] > preco * 1.01 else "valendo")
        else:
            o["situacao"] = "valendo"
        ofertas.append(o)
    campos = ("codigo", "loja", "desconto_pct", "desconto_cent", "minimo_cent", "teto_cent", "validade", "texto", "origem", "visto_em", "confirmado_em", "regra_oficial")
    return {"gerado_em": ofertas_json["gerado_em"], "link_grupo": link_grupo,
            "total": len(ofertas), "ofertas": ofertas, "produtos": produtos,
            "cupons": [{k: c.get(k) for k in campos} for c in (cupons or [])], "bot": bot or ""}
