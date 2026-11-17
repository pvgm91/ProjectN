"""Cupons lidos de grupos e canais do Telegram, com a SUA conta (API oficial, so leitura).

Configuracao (uma vez):
  1. Em https://my.telegram.org -> API development tools, crie um app e copie api_id e api_hash.
  2. No .env:  TELEGRAM_API_ID=...   TELEGRAM_API_HASH=...
  3. rodar.bat entrar telegram   (pede o seu numero e o codigo que o Telegram manda)
  4. Em config/regras.json, "cupons_telegram" -> "canais": nomes dos grupos/canais (como aparecem no
     Telegram) ou @usuario / link t.me.
Do texto das mensagens so saem os CODIGOS e as regras (desconto, minimo, validade). Links de afiliado
de outras pessoas que estiverem nas mensagens nao sao usados.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

PALAVRAS_COMUNS = {"AMAZON", "SHOPEE", "MERCADO", "LIVRE", "FRETE", "GRATIS", "LINK", "AQUI", "HOJE", "VALIDO", "OFF",
                   "CUPOM", "CUPONS", "CODIGO", "PROMO", "PROMOCAO", "DESCONTO", "APP", "SITE", "NINTENDO", "SWITCH",
                   "PIX", "BOLETO", "CARTAO", "PRIME", "MELI", "ATIVE", "RESGATE", "CLIQUE", "LOJA", "BLACK", "FRIDAY",
                   "OFERTA", "OFERTAS", "TODOS", "TODAS", "NOVO", "NOVOS", "USE", "ACIMA", "MINIMO", "LIMITE", "HTTPS", "HTTP"}
LOJAS = [("mercadolivre", r"mercado\s*livre|mercadolivre|\bmeli\b|mercado pago"), ("amazon", r"amazon"),
         ("shopee", r"shopee"), ("magalu", r"magalu|magazine luiza"), ("kabum", r"kabum"),
         ("aliexpress", r"aliexpress"), ("nuuvem", r"nuuvem"), ("eshop", r"eshop|nintendo store")]
CODIGO = re.compile(r"(?i:cupo(?:m|ns)|c[oó]digo|\bcode\b|\buse\b)\s*(?i:de desconto|promocional)?\s*[:\-–=]?\s*[`\"“'*_]*"
                    r"([A-Z0-9][A-Z0-9_-]{3,24})\b")
ENTRE_CRASES = re.compile(r"`([A-Z0-9][A-Z0-9_-]{3,24})`")
# "🎟️ CODIGO" e "CODIGO - R$ 20 OFF" / "CODIGO: 10% OFF" no comeco da linha
TICKET = re.compile(r"(?:🎟|🎫|🏷|✂|🔖)\ufe0f?\s*[`\"“'*_]*([A-Z0-9][A-Z0-9_-]{3,24})\b")
CODIGO_E_REGRA = re.compile(r"^[^A-Za-z0-9]*([A-Z0-9][A-Z0-9_-]{4,24})\s*[-–:=]\s*(?:R\$\s*\d|\d{1,2}\s*%)", re.M)
PCT = re.compile(r"(\d{1,2})\s*%\s*(?:off|de desconto|de desc|de volta|desconto)?", re.I)
VALOR = re.compile(r"R\$\s*([\d.]+(?:,\d{2})?)\s*(?:off|de desconto|de desc|reais de desconto)", re.I)
MINIMO = re.compile(r"(?:m[ií]nimo(?: de)?|acima de|compras? (?:a partir|acima) de|a partir de|pedidos? acima de)\s*R\$\s*([\d.]+(?:,\d{2})?)", re.I)
TETO = re.compile(r"(?:limitad[oa] a|m[aá]ximo de|m[aá]x\.?|teto de|at[eé])\s*R\$\s*([\d.]+(?:,\d{2})?)\s*(?:de desconto|off)", re.I)
VALIDADE = re.compile(r"(?:v[aá]lid[oa]|expira|termina|acaba|vence)[^0-9\n]{0,15}(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", re.I)


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
VALIDADE_EXTENSO = re.compile(r"(?:valid[oa]|expira|termina|acaba|vence)[^0-9\n]{0,15}(\d{1,2})\s+de\s+"
                              r"(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*(?:\s+de\s+(\d{4}))?", re.I)


class _DataExtenso:
    """Imita um match de VALIDADE (grupos dia, mes, ano) para uma data escrita por extenso."""
    def __init__(self, dia, mes, ano):
        self._g = (None, str(dia), str(mes), ano)

    def group(self, k):
        return self._g[k]


def _cent(txt):
    return int(round(float(txt.replace(".", "").replace(",", ".")) * 100))


def _sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))


def _loja(texto):
    base = _sem_acento(texto).lower()
    return next((nome for nome, rx in LOJAS if re.search(rx, base)), "")


def _regras(trecho, quando):
    """Desconto, minimo, teto e validade escritos num trecho de texto."""
    teto = TETO.search(trecho)
    pct = PCT.search(trecho)
    # "limitado a R$ 60 de desconto" e o teto, nao um desconto em reais
    valor = next((m for m in VALOR.finditer(trecho) if not (teto and teto.start() <= m.start() < teto.end())), None)
    minimo = MINIMO.search(trecho)
    validade = ""
    v = VALIDADE.search(trecho)
    if not v:                    # "vence em 30 de novembro"
        e = VALIDADE_EXTENSO.search(_sem_acento(trecho))
        if e:
            v = _DataExtenso(int(e.group(1)), MESES.index(e.group(2)[:3]) + 1, e.group(3))
    if v:
        dia, mes = int(v.group(1)), int(v.group(2))
        ano = int(v.group(3)) if v.group(3) else quando.year
        ano = ano + 2000 if ano < 100 else ano
        try:
            d = date(ano, mes, dia)
            if not v.group(3) and d < quando.date() - timedelta(days=60):   # "valido ate 05/01" dito em dezembro
                d = date(ano + 1, mes, dia)
            validade = d.isoformat()
        except ValueError:
            pass
    return {"desconto_pct": float(pct.group(1)) if pct and not valor else 0.0,
            "desconto_cent": _cent(valor.group(1)) if valor else 0,
            "minimo_cent": _cent(minimo.group(1)) if minimo else 0,
            "teto_cent": _cent(teto.group(1)) if teto else 0,
            "validade": validade}


def extrair(texto, quando=None):
    """Uma mensagem -> lista de cupons {codigo, loja, desconto_pct, desconto_cent, minimo_cent, teto_cent, validade, texto}.

    Mensagem com varios cupons: as regras e a loja de cada codigo vem das linhas em volta dele
    (a linha do codigo, a anterior e a seguinte). O que faltar ali vem da mensagem inteira.
    """
    if not texto:
        return []
    quando = quando or datetime.now(timezone.utc)
    linhas = texto.splitlines()
    inicio, pos = [], 0
    for linha in linhas:
        inicio.append(pos)
        pos += len(linha) + 1
    linha_de = lambda i: max(k for k, ini in enumerate(inicio) if ini <= i) if inicio else 0
    candidatos = sorted((m.start(1), m.group(1)) for rx in (CODIGO, ENTRE_CRASES, TICKET, CODIGO_E_REGRA)
                        for m in rx.finditer(texto))
    achados = []          # (codigo, indice da linha)
    for i, bruto in candidatos:
        c = bruto.upper().strip("-_")
        if c in PALAVRAS_COMUNS or not re.search(r"[A-Z]", c) or c.startswith("HTTP") or c in [a[0] for a in achados]:
            continue
        achados.append((c, linha_de(i)))
    if not achados:
        return []
    geral, loja_geral = _regras(texto, quando), _loja(texto)
    resumo = re.sub(r"https?://\S+", "", texto)                     # sem links de terceiros
    resumo = re.sub(r"\s+", " ", resumo).strip()[:280]
    saida = []
    for codigo, n in achados:
        if len(achados) == 1:
            regras, loja = geral, loja_geral
        else:
            perto = "\n".join(linhas[max(0, n - 1):n + 2])
            propria = _regras(linhas[n], quando)          # a regra na mesma linha do codigo vale mais
            regras = propria if (propria["desconto_pct"] or propria["desconto_cent"]) else _regras(perto, quando)
            # loja: a da propria linha; senao o "titulo de secao" mais proximo acima (ex.: "Shopee"); senao a da mensagem
            acima = next((_loja(linhas[k]) for k in range(n - 1, -1, -1) if _loja(linhas[k])), "")
            loja = _loja(linhas[n]) or acima or loja_geral
            if not (regras["desconto_pct"] or regras["desconto_cent"]):        # nada perto: usa o da mensagem
                regras = dict(regras, desconto_pct=geral["desconto_pct"], desconto_cent=geral["desconto_cent"])
            regras["validade"] = regras["validade"] or geral["validade"]
        saida.append(dict(codigo=codigo, loja=loja, texto=resumo, **regras))
    return saida


def preco_com_cupom(preco_cent, cupom):
    """Preco final aplicando o cupom, ou None se nao se aplica (minimo nao atingido ou sem valor)."""
    if cupom.get("minimo_cent") and preco_cent < cupom["minimo_cent"]:
        return None
    if cupom.get("desconto_cent"):
        desconto = cupom["desconto_cent"]
    elif cupom.get("desconto_pct"):
        desconto = int(round(preco_cent * cupom["desconto_pct"] / 100))
    else:
        return None
    if cupom.get("teto_cent"):
        desconto = min(desconto, cupom["teto_cent"])
    return max(0, preco_cent - desconto)


# ---------------------------------------------------------------- leitura do Telegram

class SemTelegram(Exception):
    pass


def cliente(env, sessao):
    try:
        from telethon.sync import TelegramClient
    except ImportError:
        raise SemTelegram("falta instalar o Telethon: rode instalar.bat")
    if not (env.get("TELEGRAM_API_ID") and env.get("TELEGRAM_API_HASH")):
        raise SemTelegram("preencha TELEGRAM_API_ID e TELEGRAM_API_HASH no .env (my.telegram.org)")
    return TelegramClient(str(sessao), int(env["TELEGRAM_API_ID"]), env["TELEGRAM_API_HASH"])


def _achar_chat(cli, nome):
    if nome.startswith("@") or "t.me/" in nome:
        return cli.get_entity(nome)
    alvo = _sem_acento(nome).lower().strip()
    for d in cli.iter_dialogs():
        if _sem_acento(d.name or "").lower().strip() == alvo:
            return d.entity
    raise SemTelegram(f"nao achei o grupo/canal '{nome}' nas suas conversas do Telegram")


def ler(env, sessao, canais, desde, por_canal=200):
    """[(nome_do_canal, datetime_utc, texto)] das mensagens desde 'desde'."""
    cli = cliente(env, sessao)
    cli.connect()
    try:
        if not cli.is_user_authorized():
            raise SemTelegram("o Telegram nao esta conectado: rode 'rodar.bat entrar telegram'")
        saida = []
        for nome in canais:
            chat = _achar_chat(cli, nome)
            for msg in cli.iter_messages(chat, limit=por_canal):
                if msg.date and msg.date < desde:
                    break
                if msg.message:
                    saida.append((nome, msg.date, msg.message))
        return saida
    finally:
        cli.disconnect()
