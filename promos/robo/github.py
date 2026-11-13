"""Envio para o GitHub pela API, com um token guardado no .env (GITHUB_TOKEN). Nao usa o git.

- publicar_painel: envia o painel (docs/index.html) para o repositorio publico da pagina.
- enviar_codigo: envia os arquivos do projeto para o repositorio privado do codigo.
O arquivo .env, o banco e o perfil do navegador NUNCA sao enviados.
"""
import base64
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
EXTENSOES = {".py", ".json", ".md", ".bat", ".html", ".example", ".gitignore", ".gitkeep", ".txt"}
PASTAS_FORA = {"__pycache__", ".git", ".venv", ".idea", "perfil_navegador", "dados"}


class ErroGitHub(Exception):
    pass


def _chamar(token, metodo, caminho, corpo=None, enviar=None):
    if enviar:
        return enviar(metodo, caminho, corpo)
    req = urllib.request.Request(
        API + caminho, method=metodo, data=json.dumps(corpo).encode("utf-8") if corpo is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "projectn-promos",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            return e.code, {}
    except urllib.error.URLError as e:
        raise ErroGitHub(f"GitHub inacessivel: {e.reason}")


def sha_git(conteudo):
    """O mesmo identificador que o git calcula para um arquivo (blob)."""
    return hashlib.sha1(b"blob %d\0" % len(conteudo) + conteudo).hexdigest()


def enviar_arquivo(token, repo, caminho, conteudo, mensagem, sha_remoto=None, enviar=None):
    """Cria ou atualiza um arquivo. Devolve 'igual', 'criado' ou 'atualizado'."""
    if sha_remoto is None:
        status, atual = _chamar(token, "GET", f"/repos/{repo}/contents/{caminho}", enviar=enviar)
        if status == 200:
            sha_remoto = atual.get("sha")
        elif status in (401, 403):
            raise ErroGitHub(f"token sem acesso ao repositorio {repo} (HTTP {status})")
    if sha_remoto == sha_git(conteudo):
        return "igual"
    corpo = {"message": mensagem, "content": base64.b64encode(conteudo).decode("ascii")}
    if sha_remoto:
        corpo["sha"] = sha_remoto
    status, resp = _chamar(token, "PUT", f"/repos/{repo}/contents/{caminho}", corpo, enviar=enviar)
    if status not in (200, 201):
        raise ErroGitHub(f"nao foi possivel enviar {caminho} para {repo} (HTTP {status}: {resp.get('message', '')})")
    return "atualizado" if sha_remoto else "criado"


def arquivos_do_projeto(raiz):
    """Arquivos que podem ir para o repositorio. Nunca inclui .env, banco ou perfil do navegador."""
    raiz = Path(raiz)
    achados = []
    for p in sorted(raiz.rglob("*")):
        rel = p.relative_to(raiz)
        if not p.is_file() or PASTAS_FORA & set(rel.parts[:-1]):
            continue
        if p.name == ".env" or p.name.startswith(".env.") and p.name != ".env.example":
            continue
        if p.suffix.lower() in EXTENSOES or p.name in EXTENSOES:
            achados.append(rel.as_posix())
    return achados


def enviar_codigo(token, repo, raiz, enviar=None):
    """Envia so o que mudou. Devolve {'criado': n, 'atualizado': n, 'igual': n}."""
    status, arvore = _chamar(token, "GET", f"/repos/{repo}/git/trees/main?recursive=1", enviar=enviar)
    if status in (401, 403):
        raise ErroGitHub(f"token sem acesso ao repositorio {repo} (HTTP {status})")
    remotos = {n["path"]: n["sha"] for n in arvore.get("tree", [])} if status == 200 else {}
    contagem = {"criado": 0, "atualizado": 0, "igual": 0}
    for rel in arquivos_do_projeto(raiz):
        conteudo = (Path(raiz) / rel).read_bytes()
        if remotos.get(rel) == sha_git(conteudo):
            contagem["igual"] += 1
            continue
        r = enviar_arquivo(token, repo, rel, conteudo, f"Atualiza {rel}", sha_remoto=remotos.get(rel) or "", enviar=enviar)
        contagem[r] += 1
    return contagem


def preparar_pagina(token, repo, pasta="", enviar=None):
    """Garante que o repositorio da pagina existe, e publico, e que o GitHub Pages esta ligado.

    pasta: "" publica a raiz do repositorio; "docs" publica a pasta /docs.
    Devolve a lista do que foi feito. Pode ser chamada varias vezes sem efeito colateral.
    """
    feito = []
    nome = repo.split("/")[1]
    status, dados = _chamar(token, "GET", f"/repos/{repo}", enviar=enviar)
    if status in (401, 403):
        raise ErroGitHub(f"o token foi recusado pelo GitHub (HTTP {status})")
    if status == 404:
        status, resp = _chamar(token, "POST", "/user/repos", {
            "name": nome, "private": False, "auto_init": True,
            "description": "Painel de ofertas do grupo de promocoes do Project N (pagina gerada automaticamente)"}, enviar=enviar)
        if status != 201:
            raise ErroGitHub(f"nao foi possivel criar o repositorio {repo} (HTTP {status}: {resp.get('message', '')})")
        feito.append("repositorio criado")
    elif dados.get("private"):
        raise ErroGitHub(f"o repositorio {repo} ainda e privado. Torne-o publico em "
                         f"https://github.com/{repo}/settings (fim da pagina, 'Change visibility') e rode de novo")
    status, resp = _chamar(token, "POST", f"/repos/{repo}/pages",
                           {"source": {"branch": "main", "path": "/" + pasta}}, enviar=enviar)
    if status == 201:
        feito.append("GitHub Pages ligado")
    elif status != 409:      # 409 = ja estava ligado
        raise ErroGitHub(f"nao foi possivel ligar o GitHub Pages (HTTP {status}: {resp.get('message', '')}). "
                         f"Ligue a mao em https://github.com/{repo}/settings/pages (branch main, pasta /{pasta})")
    return feito
