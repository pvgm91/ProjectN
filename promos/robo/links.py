"""Links curtos do Project N: uma pagina de redirecionamento por produto, publicada com o painel.

Endereco: <base>/l/<codigo>  (ex.: https://promo.projectn.com.br/l/k3f9qa)
- O codigo e fixo para cada produto (mesma loja + mesmo id = mesmo link), entao um link ja
  postado continua valendo nas proximas coletas. Paginas antigas nunca sao apagadas.
- A pagina leva na hora para o link da loja com a identificacao de afiliado e tem titulo e
  foto do produto, para a previa no WhatsApp.
"""
import hashlib
import html
import re
from pathlib import Path

ALFABETO = "abcdefghijkmnpqrstuvwxyz23456789"     # sem 0/o, 1/l: facil de ler e digitar


def codigo(loja, id_loja, tamanho=6):
    n = int(hashlib.sha1(f"{loja}:{id_loja}".encode("utf-8")).hexdigest(), 16)
    saida = ""
    for _ in range(tamanho):
        n, r = divmod(n, len(ALFABETO))
        saida += ALFABETO[r]
    return saida


def base(regras):
    """Endereco base dos links: o dominio proprio, se configurado; senao, o do GitHub Pages."""
    lc = regras.get("links_curtos") or {}
    if lc.get("dominio"):
        return f"https://{lc['dominio'].strip().strip('/')}/l/"
    dono, nome = ((regras.get("github") or {}).get("repo_painel") or "/").split("/")
    return f"https://{dono}.github.io/{nome}/l/" if dono else ""


def ativo(regras):
    return bool((regras.get("links_curtos") or {}).get("ativo")) and bool(base(regras))


def pagina(destino, titulo, imagem=""):
    imagem = re.sub(r"\._[A-Z0-9_,]+_(\.(?:jpg|jpeg|png|webp))$", r"\1", imagem or "", flags=re.I)   # Amazon: foto grande
    d, t = html.escape(destino, quote=True), html.escape(titulo, quote=True)
    img = f'<meta property="og:image" content="{html.escape(imagem, quote=True)}">' if imagem else ""
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{t}</title>
<meta property="og:title" content="{t}">
<meta property="og:description" content="Oferta do grupo de promoções do Project N">
<meta property="og:site_name" content="Project N">
{img}
<meta http-equiv="refresh" content="0;url={d}">
<link rel="canonical" href="{d}">
<script>location.replace({destino!r});</script>
<style>body{{font:16px system-ui,sans-serif;margin:40px 16px;text-align:center;color:#333}}a{{color:#c8102e}}</style>
</head><body><p>Abrindo a oferta… <a href="{d}">Clique aqui se não abrir.</a></p></body></html>
"""


def gerar(pasta_painel, produtos):
    """produtos: [{'loja','id_loja','destino','titulo','imagem'}]. Grava docs/l/<codigo>.html.

    Devolve {chave (loja, id_loja): codigo}. So reescreve o arquivo se o conteudo mudou.
    """
    pasta = Path(pasta_painel) / "l"
    pasta.mkdir(parents=True, exist_ok=True)
    codigos = {}
    for p in produtos:
        if not p.get("destino"):
            continue
        c = codigo(p["loja"], p["id_loja"])
        conteudo = pagina(p["destino"], p.get("titulo") or "Oferta", p.get("imagem") or "")
        arq = pasta / f"{c}.html"
        if not arq.exists() or arq.read_text(encoding="utf-8") != conteudo:
            arq.write_text(conteudo, encoding="utf-8")
        codigos[(p["loja"], p["id_loja"])] = c
    return codigos
