"""Remover produtos pelo painel.

O botao "Remover" do painel abre o bot do Telegram com /start rm_<numero>. A cada coleta o robo le
essas mensagens (so de quem esta autorizado), tira o produto do painel e para de acompanha-lo.
Tambem da para mandar direto ao bot:  /remover 123 456   ou   /voltar 123
"""
import re

from . import db

PADRAO = re.compile(r"^/(?:start\s+)?(rm|remover|volta|voltar)[_\s]+([\d_\s,]+)$", re.I)


def ler_pedido(texto):
    """'/start rm_123' -> ('remover', [123]); '/voltar 5 6' -> ('voltar', [5, 6]); outro texto -> None."""
    m = PADRAO.match(texto.strip())
    if not m:
        return None
    acao = "voltar" if m.group(1).lower().startswith("volta") else "remover"
    ids = [int(x) for x in re.findall(r"\d+", m.group(2))]
    return (acao, ids) if ids else None


def processar(con, avisos, quando):
    """Le os pedidos mandados ao bot e aplica. Devolve quantos produtos mudaram."""
    mudou = 0
    for chat, texto, nome in avisos.comandos():
        pedido = ler_pedido(texto)
        if not pedido:
            continue
        if chat not in avisos.autorizados():
            avisos.responder(chat, f"Você ainda não está autorizado a mexer no painel. Peça para o Paulo rodar:\n"
                                   f"rodar.bat autorizar {chat}")
            continue
        acao, ids = pedido
        feitos = []
        for pid in ids:
            titulo = db.marcar_removido(con, pid, quando, voltar=(acao == "voltar"))
            if titulo:
                feitos.append(f"• {titulo[:70]}")
                mudou += 1
        if feitos:
            cab = "🗑️ Removido do painel (o robô para de acompanhar):" if acao == "remover" else "↩️ De volta ao painel:"
            rodape = "\n\nPara desfazer: /voltar " + " ".join(map(str, ids)) if acao == "remover" else ""
            avisos.responder(chat, cab + "\n" + "\n".join(feitos) + rodape + "\n\nO painel atualiza na próxima coleta.")
        else:
            avisos.responder(chat, "Não achei esse produto no banco do robô.")
    return mudou
