"""Gera o painel (docs/index.html): uma pagina unica, sem dependencias, com ofertas, produtos e historico.

O modelo fica em painel_modelo.html; aqui so entram os dados. Abre direto no navegador
(abrir_painel.bat) e e o mesmo arquivo publicado no GitHub Pages.
"""
import base64
import json
import os
import shutil
from pathlib import Path

MODELO = Path(__file__).with_name("painel_modelo.html")


ITERACOES = 310000


class ErroCifra(Exception):
    pass


def cifrar(texto, senha, sal):
    """AES-256-GCM com chave derivada da senha (PBKDF2-SHA256). O navegador abre com a mesma senha."""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        raise ErroCifra("falta o pacote 'cryptography': rode instalar.bat")
    chave = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=ITERACOES).derive(senha.encode("utf-8"))
    iv = os.urandom(12)
    dados = AESGCM(chave).encrypt(iv, texto.encode("utf-8"), None)
    b = lambda x: base64.b64encode(x).decode("ascii")
    return {"cifrado": 1, "sal": b(sal), "iv": b(iv), "iteracoes": ITERACOES, "dados": b(dados)}


def montar(dados, senha="", sal=b""):
    """dados = dicionario de exportar.dados_do_painel. Com senha, os dados vao cifrados para a pagina."""
    dados = {"link_grupo": "", "produtos": [], **dados}
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    if senha:
        if len(sal) < 16:
            raise ErroCifra("sal invalido")
        texto = json.dumps(cifrar(texto, senha, sal))
    return MODELO.read_text(encoding="utf-8").replace("__DADOS__", texto.replace("</", "<\\/"))


def copiar_molduras(pasta_painel):
    """Copia as molduras da arte (robo/arte/*.png) para a pasta do painel, se mudaram."""
    destino = Path(pasta_painel) / "arte"
    destino.mkdir(parents=True, exist_ok=True)
    for origem in Path(__file__).with_name("arte").glob("*.png"):
        alvo = destino / origem.name
        if not alvo.exists() or alvo.read_bytes() != origem.read_bytes():
            shutil.copyfile(origem, alvo)
