"""Decide se um titulo pertence ao universo Nintendo e a qual produto ele corresponde."""
import re
import unicodedata


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


def contem(texto_norm, termo):
    """Casa o termo como palavra inteira: 'mario' nao casa com 'armario'."""
    padrao = r"(?<![a-z0-9])" + re.escape(normalizar(termo)) + r"(?![a-z0-9])"
    return re.search(padrao, texto_norm) is not None


def classificar(titulo, catalogo):
    """Devolve a categoria do titulo, ou None se nao interessa ao grupo."""
    t = normalizar(titulo)
    if any(contem(t, b) for b in catalogo.get("bloqueados", [])):
        return None
    for grupo in catalogo.get("grupos", []):
        if not any(contem(t, termo) for termo in grupo["qualquer"]):
            continue
        tambem = grupo.get("tambem")
        if tambem and not any(contem(t, termo) for termo in tambem):
            continue
        return grupo["categoria"]
    return None


def identificar_produto(titulo, catalogo):
    """Devolve (chave, preco_sugerido_cent) do produto cadastrado que casa com o titulo."""
    t = normalizar(titulo)
    for p in catalogo.get("produtos", []):
        if p.get("exemplo"):
            continue
        if all(contem(t, termo) for termo in p["termos"]):
            return p["chave"], int(round(float(p.get("preco_sugerido_reais") or 0) * 100))
    return "", 0
