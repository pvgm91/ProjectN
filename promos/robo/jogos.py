"""Lista de jogos em midia fisica procurados pelo nome (config/jogos.txt), com rodizio.

Sao muitos jogos, entao a cada coleta o robo pega so alguns da fila de cada loja e continua de
onde parou na proxima. Assim todos sao vistos ao longo do dia sem encher a loja de visitas.
"""
import json
from pathlib import Path

CONSULTA = {"Switch 2": "{t} nintendo switch 2", "Switch": "{t} nintendo switch"}


def ler_jogos(caminho):
    """[(plataforma, titulo)] na ordem do arquivo, sem repetidos."""
    try:
        linhas = Path(caminho).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    plataforma, vistos, saida = "Switch", set(), []
    for l in linhas:
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        if l.startswith("[") and l.endswith("]"):
            plataforma = l[1:-1].strip()
            continue
        chave = (plataforma, l.lower())
        if chave not in vistos:
            vistos.add(chave)
            saida.append((plataforma, l))
    return saida


def consulta(plataforma, titulo):
    """Texto da busca na loja: 'Mario Kart World nintendo switch 2'."""
    return CONSULTA.get(plataforma, "{t} " + plataforma).format(t=titulo)


def rodizio(lista, quantos, arquivo, chave):
    """Os proximos 'quantos' itens da lista para esta chave (ex.: 'amazon'), guardando a posicao."""
    if not lista or quantos <= 0:
        return []
    arquivo = Path(arquivo)
    try:
        pos = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pos = {}
    inicio = int(pos.get(chave, 0)) % len(lista)
    quantos = min(quantos, len(lista))
    escolhidos = [lista[(inicio + i) % len(lista)] for i in range(quantos)]
    pos[chave] = (inicio + quantos) % len(lista)
    try:
        arquivo.write_text(json.dumps(pos), encoding="utf-8")
    except OSError:
        pass
    return escolhidos
