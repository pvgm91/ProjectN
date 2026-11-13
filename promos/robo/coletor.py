"""Fluxo de um ciclo: item da loja -> filtros -> historico -> sinais -> oferta."""
from . import catalogo as cat
from . import db, detector, reputacao
from .fontes.base import ErroDaFonte


def processar(con, itens, catalogo, regras, agora, verificador=None, max_verificacoes=8):
    """Processa uma lista de Item. Devolve um resumo com contagens.

    verificador: funcao item -> item, usada por lojas em que a busca nao informa o vendedor
    (Amazon pelo site). Nelas o produto e acompanhado sem vendedor e so e conferido, na
    pagina do produto, quando algum sinal de oferta dispara.
    """
    resumo = {"recebidos": 0, "fora_do_catalogo": 0, "reprovados_reputacao": 0,
              "acompanhados": 0, "ofertas_novas": 0, "verificados": 0}
    vistos = set()
    if verificador:      # confere primeiro os maiores descontos, porque ha um limite por ciclo
        itens = sorted(itens, key=lambda i: -((i.original_cent - i.preco_cent) / i.original_cent if i.original_cent else 0))
    for item in itens:
        chave_item = (item.loja, item.id_loja)
        if chave_item in vistos:      # a mesma oferta aparece em varias buscas
            continue
        vistos.add(chave_item)
        resumo["recebidos"] += 1

        categoria = item.categoria or cat.classificar(item.titulo, catalogo)
        if not categoria:
            resumo["fora_do_catalogo"] += 1
            continue

        if verificador and not item.vendedor:       # reaproveita o vendedor ja conferido antes
            antigo = db.vendedor_conhecido(con, item.loja, item.id_loja)
            if antigo:
                item.vendedor, item.selo = antigo
        sem_vendedor = bool(verificador) and not item.vendedor
        if not sem_vendedor and not reputacao.aprovado(item, regras)[0]:
            resumo["reprovados_reputacao"] += 1
            continue

        chave_produto, sugerido = cat.identificar_produto(item.titulo, catalogo)
        produto_id = db.salvar_item(con, item, categoria, chave_produto, agora)
        # As referencias sao lidas ANTES de gravar o preco de agora.
        historico = db.minimos_diarios(con, produto_id, agora)
        outras = db.precos_outras_lojas(con, chave_produto, item.loja, agora)
        db.gravar_preco(con, produto_id, item.preco_cent, item.original_cent, agora)
        resumo["acompanhados"] += 1

        sinais = detector.detectar(item.preco_cent, item.original_cent, sugerido, outras, historico, regras)
        if sinais and sem_vendedor:
            if resumo["verificados"] >= max_verificacoes:
                continue                    # fica para o proximo ciclo
            try:
                item = verificador(item)
            except ErroDaFonte:
                continue
            resumo["verificados"] += 1
            db.salvar_item(con, item, categoria, chave_produto, agora)
            if not reputacao.aprovado(item, regras)[0]:
                resumo["reprovados_reputacao"] += 1
                continue
            sinais = detector.detectar(item.preco_cent, item.original_cent, sugerido, outras, historico, regras)
        elif sinais and bool(verificador) and not reputacao.aprovado(item, regras)[0]:
            continue
        if sinais and db.registrar_oferta(con, produto_id, item.preco_cent, sinais, regras, agora):
            resumo["ofertas_novas"] += 1
    con.commit()
    return resumo
