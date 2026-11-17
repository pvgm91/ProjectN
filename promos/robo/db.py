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
    primeiro_visto TEXT, ultimo_visto TEXT, validade TEXT DEFAULT '', parcelas TEXT DEFAULT '', prevenda TEXT DEFAULT '',
    importado TEXT DEFAULT '', removido TEXT DEFAULT '',
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
CREATE TABLE IF NOT EXISTS cupons (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL, loja TEXT DEFAULT '',
    desconto_pct REAL DEFAULT 0, desconto_cent INTEGER DEFAULT 0, minimo_cent INTEGER DEFAULT 0, teto_cent INTEGER DEFAULT 0,
    validade TEXT DEFAULT '', texto TEXT DEFAULT '', origem TEXT DEFAULT '',
    primeiro_visto TEXT, visto_em TEXT,
    UNIQUE (codigo, loja)
);
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
    for coluna in ("validade", "parcelas", "prevenda", "importado", "removido"):      # banco criado por uma versao anterior
        if coluna not in colunas:
            con.execute(f"ALTER TABLE produtos ADD COLUMN {coluna} TEXT DEFAULT ''")
    colunas = [l[1] for l in con.execute("PRAGMA table_info(cupons)")]
    for coluna in ("confirmado_em", "regra_oficial"):
        if coluna not in colunas:
            con.execute(f"ALTER TABLE cupons ADD COLUMN {coluna} TEXT DEFAULT ''")
    return con


def confirmar_cupom(con, codigo, loja, texto_oficial, regras, quando):
    """Cupom achado na pagina de cupons da propria loja: guarda o texto oficial e usa as regras de la."""
    sets, vals = ["confirmado_em=?", "regra_oficial=?"], [_iso(quando), texto_oficial[:400]]
    for k in ("desconto_pct", "desconto_cent", "minimo_cent", "teto_cent", "validade"):
        if regras.get(k):
            sets.append(f"{k}=?")
            vals.append(regras[k])
    con.execute(f"UPDATE cupons SET {', '.join(sets)} WHERE codigo=? AND loja=?", vals + [codigo, loja])


def salvar_item(con, item, categoria, chave_produto, agora):
    """Cria ou atualiza o produto e devolve o id."""
    ts = _iso(agora)
    con.execute(
        """INSERT INTO produtos (loja, id_loja, titulo, categoria, chave_produto, url, url_afiliado,
               imagem, vendedor, selo, nota, vendas, comissao_pct, primeiro_visto, ultimo_visto, validade, parcelas, prevenda, importado)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (loja, id_loja) DO UPDATE SET
               titulo=excluded.titulo, categoria=excluded.categoria,
               chave_produto=excluded.chave_produto, url=excluded.url,
               url_afiliado=excluded.url_afiliado, imagem=excluded.imagem,
               vendedor=excluded.vendedor, selo=excluded.selo, nota=excluded.nota,
               vendas=excluded.vendas, comissao_pct=excluded.comissao_pct, validade=excluded.validade, parcelas=excluded.parcelas, prevenda=excluded.prevenda,
               importado=CASE WHEN excluded.importado<>'' THEN excluded.importado ELSE importado END,
               ultimo_visto=excluded.ultimo_visto""",
        (item.loja, item.id_loja, item.titulo, categoria, chave_produto, item.url,
         item.url_afiliado, item.imagem, item.vendedor, item.selo, item.nota, item.vendas,
         item.comissao_pct, ts, ts, item.validade, item.parcelas, item.prevenda, item.importado))
    return con.execute("SELECT id FROM produtos WHERE loja=? AND id_loja=?",
                       (item.loja, item.id_loja)).fetchone()["id"]


def esta_removido(con, loja, id_loja):
    l = con.execute("SELECT removido FROM produtos WHERE loja=? AND id_loja=?", (loja, id_loja)).fetchone()
    return bool(l and l["removido"])


def marcar_removido(con, produto_id, quando, voltar=False):
    """Tira (ou devolve) um produto do painel e da coleta. Devolve o titulo, ou None se o id nao existe."""
    l = con.execute("SELECT titulo FROM produtos WHERE id=?", (produto_id,)).fetchone()
    if not l:
        return None
    con.execute("UPDATE produtos SET removido=? WHERE id=?", ("" if voltar else _iso(quando), produto_id))
    con.commit()
    return l["titulo"]


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
    """Ofertas abertas. Se o preco caiu de novo, so a oferta mais recente do produto aparece."""
    return con.execute(
        """SELECT o.*, p.loja, p.id_loja, p.titulo, p.categoria, p.url, p.url_afiliado, p.imagem,
                  p.vendedor, p.selo, p.nota, p.vendas, p.comissao_pct, p.validade, p.parcelas, p.importado
           FROM ofertas o JOIN produtos p ON p.id = o.produto_id
           WHERE o.status=? AND COALESCE(p.removido, '') = ''
             AND o.id = (SELECT MAX(o2.id) FROM ofertas o2 WHERE o2.produto_id = o.produto_id AND o2.status = o.status)
           ORDER BY o.desconto_pct DESC, o.detectada_em DESC LIMIT ?""",
        (status, limite)).fetchall()


def salvar_cupom(con, c, origem, quando):
    """Grava o cupom. Mesmo codigo com e sem loja identificada vira um cupom so (o que tem loja)."""
    ts = _iso(quando)
    if not c["loja"]:
        com_loja = con.execute("SELECT id FROM cupons WHERE codigo=? AND loja<>''", (c["codigo"],)).fetchone()
        if com_loja:
            con.execute("UPDATE cupons SET visto_em=MAX(visto_em, ?) WHERE id=?", (ts, com_loja["id"]))
            return
    else:
        sem_loja = con.execute("SELECT * FROM cupons WHERE codigo=? AND loja=''", (c["codigo"],)).fetchone()
        if sem_loja:      # aproveita a regra que so a outra mensagem tinha
            c = dict(c)
            for k in ("desconto_pct", "desconto_cent", "minimo_cent", "teto_cent", "validade"):
                c[k] = c[k] or sem_loja[k]
            con.execute("DELETE FROM cupons WHERE id=?", (sem_loja["id"],))
    con.execute(
        """INSERT INTO cupons (codigo, loja, desconto_pct, desconto_cent, minimo_cent, teto_cent, validade, texto, origem,
               primeiro_visto, visto_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (codigo, loja) DO UPDATE SET
               desconto_pct=CASE WHEN excluded.desconto_pct>0 OR excluded.desconto_cent>0 THEN excluded.desconto_pct ELSE desconto_pct END,
               desconto_cent=CASE WHEN excluded.desconto_pct>0 OR excluded.desconto_cent>0 THEN excluded.desconto_cent ELSE desconto_cent END,
               minimo_cent=CASE WHEN excluded.minimo_cent>0 THEN excluded.minimo_cent ELSE minimo_cent END,
               teto_cent=CASE WHEN excluded.teto_cent>0 THEN excluded.teto_cent ELSE teto_cent END, validade=CASE WHEN excluded.validade<>'' THEN excluded.validade ELSE validade END,
               texto=excluded.texto, origem=excluded.origem,
               visto_em=CASE WHEN excluded.visto_em > visto_em THEN excluded.visto_em ELSE visto_em END""",
        (c["codigo"], c["loja"], c["desconto_pct"], c["desconto_cent"], c["minimo_cent"], c["teto_cent"], c["validade"],
         c["texto"], origem, ts, ts))


def listar_cupons(con, agora, horas=3, lojas=None):
    """Cupons postados nas ultimas 'horas' e ainda nao vencidos, do mais recente para o mais antigo."""
    desde, hoje = _iso(agora - timedelta(hours=horas)), _iso(agora)[:10]
    linhas = [dict(l) for l in con.execute(
        "SELECT * FROM cupons WHERE visto_em>=? AND (validade='' OR validade>=?) ORDER BY visto_em DESC", (desde, hoje))]
    com_loja = {l["codigo"] for l in linhas if l["loja"]}
    return [l for l in linhas if (l["loja"] or l["codigo"] not in com_loja)
            and (not lojas or not l["loja"] or l["loja"] in lojas)]
