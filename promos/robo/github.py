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
EXTENSOES = {".py", ".json", ".md", ".bat", ".html", ".example", ".gitignore", ".gitkeep", ".txt", ".png"}
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
    """Arquivos que podem ir para o repositorio. Nunca inclui .env, banco, perfil do navegador nem a pasta docs
    (o painel tem milhares de links curtos; mandados um a um, travavam o GitHub Pages)."""
    raiz = Path(raiz)
    achados = []
    for p in sorted(raiz.rglob("*")):
        rel = p.relative_to(raiz)
        if not p.is_file() or PASTAS_FORA & set(rel.parts[:-1]):
            continue
        if rel.parts[0] == "docs":      # painel e links curtos: quem envia e o 'publicar', num commit so
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


def enviar_lote(token, repo, textos, mensagem, ramo="main", enviar=None):
    """Envia varios arquivos de texto num commit so; so os que mudaram. Devolve quantos mudaram.

    textos = {caminho_no_repositorio: conteudo (str)}.
    """
    st, ref = _chamar(token, "GET", f"/repos/{repo}/git/ref/heads/{ramo}", enviar=enviar)
    if st != 200:
        raise ErroGitHub(f"nao foi possivel ler o repositorio {repo} (HTTP {st}: {ref.get('message', '')})")
    commit_sha = ref["object"]["sha"]
    st, commit = _chamar(token, "GET", f"/repos/{repo}/git/commits/{commit_sha}", enviar=enviar)
    arvore_sha = commit["tree"]["sha"]
    st, arvore = _chamar(token, "GET", f"/repos/{repo}/git/trees/{arvore_sha}?recursive=1", enviar=enviar)
    remotos = {n["path"]: n["sha"] for n in arvore.get("tree", []) if n.get("type") == "blob"}
    mudados = [{"path": c, "mode": "100644", "type": "blob", "content": t}
               for c, t in sorted(textos.items()) if remotos.get(c) != sha_git(t.encode("utf-8"))]
    if not mudados:
        return 0
    st, nova = _chamar(token, "POST", f"/repos/{repo}/git/trees", {"base_tree": arvore_sha, "tree": mudados}, enviar=enviar)
    if st != 201:
        raise ErroGitHub(f"nao foi possivel montar o envio (HTTP {st}: {nova.get('message', '')})")
    st, novo = _chamar(token, "POST", f"/repos/{repo}/git/commits",
                       {"message": mensagem, "tree": nova["sha"], "parents": [commit_sha]}, enviar=enviar)
    if st != 201:
        raise ErroGitHub(f"nao foi possivel criar o commit (HTTP {st}: {novo.get('message', '')})")
    st, r = _chamar(token, "PATCH", f"/repos/{repo}/git/refs/heads/{ramo}", {"sha": novo["sha"]}, enviar=enviar)
    if st != 200:
        raise ErroGitHub(f"nao foi possivel atualizar o ramo {ramo} (HTTP {st}: {r.get('message', '')})")
    return len(mudados)


def definir_dominio(token, repo, dominio, enviar=None):
    """Garante o dominio proprio no GitHub Pages. Erro aqui so avisa: o CNAME no repositorio ja basta."""
    st, atual = _chamar(token, "GET", f"/repos/{repo}/pages", enviar=enviar)
    if st == 200 and (atual.get("cname") or "") == dominio:
        return False
    st, r = _chamar(token, "PUT", f"/repos/{repo}/pages", {"cname": dominio}, enviar=enviar)
    if st not in (200, 204):
        print(f"[aviso] nao consegui definir o dominio {dominio} no GitHub Pages (HTTP {st}); "
              f"defina em https://github.com/{repo}/settings/pages")
        return False
    return True
