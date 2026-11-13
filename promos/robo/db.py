"""Banco SQLite: produtos, historico de precos e ofertas detectadas."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

ESQUEMA = """
CREATE TABLE IF NOT EXISTS produtos (
    id INTEGER PRIMARY KEY,
    loja TEXT NOT NULL, id_loja TEXT NOT NULL,
    titulo TEXT, categoria TEXT, chave_produto TEXT DEFAULT '',
    url TEXT, url_afiliado TEXT, imagem TEXT,
    vendedor TEXT, selo TEXT, nota REAL, vendas INTEGER, comissao_pct REAL,
    primeiro_visto TEXT, ultimo_visto TEXT, validade TEXT DEFAULT '', parcelas TEXT DEFAULT '',
    UNIQUE (loja, id_loja)
);
CREATE TABLE IF NOT EXISTS precos (
    id INTEGER PRIMARY KEY,
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    coletado_em TEXT NOT NULL,
    preco_cent INTEGER NOT NULL,
    original_cent INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_precos ON precos (produto_id, coletado_em);
CREATE TABLE IF NOT EXISTS ofertas (
    id INTEGER PRIMARY KEY,
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    detectada_em TEXT NOT NULL,
    preco_cent INTEGER NOT NULL,
    referencia_cent INTEGER, desconto_pct REAL,
    sinais TEXT,
    status TEXT DEFAULT 'nova'   -- nova | aprovada | descartada | postada
);
CREATE INDEX IF NOT EXISTS ix_ofertas ON ofertas (produto_id, detectada_em);
"""

REGRAVAR_APOS_HORAS = 6  # preco igual so e regravado depois desse intervalo


def agora_utc():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _de_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def conectar(caminho):
    con = sqlite3.connect(str(caminho))
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    colunas = [l[1] for l in con.execute("PRAGMA table_info(produtos)")]
    for coluna in ("validade", "parcelas"):      # banco criado por uma versao anterior
        if coluna not in colunas:
            con.execute(f"ALTER TABLE produtos ADD COLUMN {coluna} TEXT DEFAULT ''")
    return con


def salvar_item(con, item, categoria, chave_produto, agora):
    """Cria ou atualiza o produto e devolve o id."""
    ts = _iso(agora)
    con.execute(
        """INSERT INTO produtos (loja, id_loja, titulo, categoria, chave_produto, url, url_afiliado,
               imagem, vendedor, selo, nota, vendas, comissao_pct, primeiro_visto, ultimo_visto, validade, parcelas)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (loja, id_loja) DO UPDATE SET
               titulo=excluded.titulo, categoria=excluded.categoria,
               chave_produto=excluded.chave_produto, url=excluded.url,
               url_afiliado=excluded.url_afiliado, imagem=excluded.imagem,
               vendedor=excluded.vendedor, selo=excluded.selo, nota=excluded.nota,
               vendas=excluded.vendas, comissao_pct=excluded.comissao_pct, validade=excluded.validade, parcelas=excluded.parcelas,
               ultimo_visto=excluded.ultimo_visto""",
        (item.loja, item.id_loja, item.titulo, categoria, chave_produto, item.url,
         item.url_afiliado, item.imagem, item.vendedor, item.selo, item.nota, item.vendas,
         item.comissao_pct, ts, ts, item.validade, item.parcelas))
    return con.execute("SELECT id FROM produtos WHERE loja=? AND id_loja=?",
                       (item.loja, item.id_loja)).fetchone()["id"]


def vendedor_conhecido(con, loja, id_loja):
    """(vendedor, selo) ja conferido para este anuncio, ou None."""
    l = con.execute("SELECT vendedor, selo FROM produtos WHERE loja=? AND id_loja=?", (loja, id_loja)).fetchone()
    return (l["vendedor"], l["selo"] or "") if l and l["vendedor"] else None


def minimos_diarios(con, produto_id, agora):
    """Menor preco de cada dia ANTERIOR a hoje (hoje nao entra na referencia)."""
    hoje = _iso(agora)[:10]
    linhas = con.execute(
        """SELECT substr(coletado_em, 1, 10) AS dia, MIN(preco_cent) AS menor
           FROM precos WHERE produto_id=? AND substr(coletado_em, 1, 10) < ?
           GROUP BY dia ORDER BY dia""", (produto_id, hoje)).fetchall()
    return [l["menor"] for l in linhas]


def gravar_preco(con, produto_id, preco_cent, original_cent, agora):
    """Grava no historico se o preco mudou ou se o ultimo registro esta velho."""
    ultimo = con.execute(
        "SELECT coletado_em, preco_cent FROM precos WHERE produto_id=? ORDER BY coletado_em DESC LIMIT 1",
        (produto_id,)).fetchone()
    if ultimo and ultimo["preco_cent"] == preco_cent:
        if agora - _de_iso(ultimo["coletado_em"]) < timedelta(hours=REGRAVAR_APOS_HORAS):
            return False
    con.execute("INSERT INTO precos (produto_id, coletado_em, preco_cent, original_cent) VALUES (?,?,?,?)",
                (produto_id, _iso(agora), preco_cent, original_cent))
    return True


def precos_outras_lojas(con, chave_produto, loja, agora, horas=24):
    """Preco mais recente (ultimas 24h) do mesmo produto em cada outra loja: o menor por loja."""
    if not chave_produto:
        return []
    desde = _iso(agora - timedelta(hours=horas))
    linhas = con.execute(
        """SELECT p.loja, MIN(x.preco_cent) AS menor
           FROM produtos p JOIN precos x ON x.produto_id = p.id
           WHERE p.chave_produto=? AND p.loja<>? AND x.coletado_em>=?
           GROUP BY p.loja""", (chave_produto, loja, desde)).fetchall()
    return [l["menor"] for l in linhas]


def registrar_oferta(con, produto_id, preco_cent, sinais, regras, agora):
    """Grava a oferta, a menos que a mesma ja tenha sido registrada ha pouco.

    Repete so se passou o prazo de regras.json ou se o preco caiu mais um pouco.
    """
    desde = _iso(agora - timedelta(hours=regras.get("repetir_oferta_apos_horas", 48)))
    anterior = con.execute(
        "SELECT preco_cent FROM ofertas WHERE produto_id=? AND detectada_em>=? ORDER BY preco_cent LIMIT 1",
        (produto_id, desde)).fetchone()
    if anterior:
        queda = (anterior["preco_cent"] - preco_cent) / anterior["preco_cent"] * 100
        if queda < regras.get("nova_queda_min_pct", 3):
            return None
    melhor = sinais[0]
    cur = con.execute(
        """INSERT INTO ofertas (produto_id, detectada_em, preco_cent, referencia_cent, desconto_pct, sinais)
           VALUES (?,?,?,?,?,?)""",
        (produto_id, _iso(agora), preco_cent, melhor["referencia_cent"], melhor["pct"],
         json.dumps(sinais, ensure_ascii=False)))
    return cur.lastrowid


def listar_ofertas(con, status="nova", limite=100):
    return con.execute(
        """SELECT o.*, p.loja, p.titulo, p.categoria, p.url, p.url_afiliado, p.imagem,
                  p.vendedor, p.selo, p.nota, p.vendas, p.comissao_pct, p.validade, p.parcelas
           FROM ofertas o JOIN produtos p ON p.id = o.produto_id
           WHERE o.status=? ORDER BY o.desconto_pct DESC, o.detectada_em DESC LIMIT ?""",
        (status, limite)).fetchall()
