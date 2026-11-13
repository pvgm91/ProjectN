"""Carrega configuracao (JSON) e segredos (.env). So biblioteca padrao."""
import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent  # pasta promos/


def carregar_json(nome):
    with open(RAIZ / "config" / nome, encoding="utf-8") as f:
        return json.load(f)


def carregar_env(caminho=None):
    """Le pares CHAVE=valor do .env. Variaveis ja definidas no sistema tem prioridade."""
    caminho = Path(caminho) if caminho else RAIZ / ".env"
    valores = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            valores[chave.strip()] = valor.strip().strip('"').strip("'")
    for chave in list(valores) + ["SHOPEE_APP_ID", "SHOPEE_SECRET"]:
        if os.environ.get(chave):
            valores[chave] = os.environ[chave]
    return valores
