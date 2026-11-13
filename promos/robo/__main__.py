"""Robo de promocoes do Project N.

Uso (dentro da pasta promos):
    rodar.bat coletar      uma coleta em todas as lojas configuradas
    rodar.bat vigiar       coleta sem parar, no intervalo de regras.json
    rodar.bat ofertas      mostra as ofertas novas, com o texto pronto para o grupo
    rodar.bat adicionar    cadastra uma oferta a mao (ex.: Mercado Livre)
    rodar.bat testar amazon   uma busca de teste (tambem: testar mercadolivre, testar shopee)
    rodar.bat entrar mercadolivre   login unico no navegador do robo
    rodar.bat publicar        envia o painel para a pagina online
    rodar.bat enviar-codigo   envia o codigo para o repositorio privado no GitHub
    rodar.bat status       quantos produtos e precos ja estao no banco
    rodar.bat demo         roda o fluxo inteiro com dados FICTICIOS, sem chaves
"""
import argparse
import json
import sys
import time
from datetime import timedelta

from . import config, db, exportar, github, painel
from .coletor import processar
from .fontes.amazon import Amazon
from .fontes.amazon_site import AmazonSite
from .navegador import Navegador
from .fontes.eshop import Eshop
from .fontes.base import ErroDaFonte, Item, SemCredenciais, para_centavos
from .fontes.mercadolivre import MercadoLivre
from .fontes.mercadolivre_site import ENTRADA, MercadoLivreSite
from .fontes.shopee import Shopee, converter

DADOS = config.RAIZ / "dados"
FONTES = [Eshop, Shopee, Amazon, MercadoLivre]
PAINEL = config.RAIZ.parent / "docs" / "index.html"


def _exportar(con, regras, arquivo):
    ofertas = db.listar_ofertas(con, "nova")
    dados = exportar.gravar_json(ofertas, arquivo, regras["link_grupo"], db._iso(db.agora_utc()))
    if arquivo.name == "ofertas.json":
        PAINEL.parent.mkdir(exist_ok=True)
        PAINEL.write_text(painel.montar(dados), encoding="utf-8")
    return ofertas


def _criar_fonte(classe, env, regras):
    """Amazon: usa o site (navegador) quando 'amazon_pelo_site' esta ligado; senao, a API."""
    if classe is Amazon and regras.get("amazon_pelo_site"):
        nav = Navegador(DADOS / "perfil_navegador", visivel=regras.get("navegador_visivel", False))
        return AmazonSite(env, nav)
    if classe is MercadoLivre and regras.get("mercadolivre_pelo_site"):
        nav = Navegador(DADOS / "perfil_navegador", visivel=regras.get("navegador_visivel", False))
        return MercadoLivreSite(env, nav)
    return classe(env)


def cmd_coletar(args):
    catalogo, regras, env = config.carregar_json("catalogo.json"), config.carregar_json("regras.json"), config.carregar_env()
    con = db.conectar(DADOS / "promos.db")
    c = regras["coleta"]
    ativas = 0
    for classe in FONTES:
        if classe.nome not in regras.get("lojas_ativas", [c.nome for c in FONTES]):
            continue
        try:
            fonte = _criar_fonte(classe, env, regras)
        except SemCredenciais as e:
            print(f"[pulada] {e}")
            continue
        ativas += 1
        itens, falhas = [], 0
        if not getattr(fonte, "por_palavra", True):
            try:
                itens = fonte.coletar()
                print(f"  {fonte.nome}: {len(itens)} itens")
            except ErroDaFonte as e:
                print(f"[erro] {fonte.nome}: {e}")
        for palavra in catalogo["buscas"] if getattr(fonte, "por_palavra", True) else []:
            try:
                achados = fonte.buscar(palavra, c["paginas_por_busca"], c["itens_por_pagina"], c["pausa_entre_chamadas_seg"])
            except (ErroDaFonte, SemCredenciais) as e:
                print(f"[erro] {fonte.nome} / '{palavra}': {e}")
                falhas += 1
                if getattr(fonte, "bloqueada", False) or isinstance(e, SemCredenciais) or falhas >= 2:
                    print(f"[{fonte.nome}] coleta interrompida neste ciclo")
                    break
                continue
            print(f"  {fonte.nome} / '{palavra}': {len(achados)} itens")
            itens += achados
            time.sleep(c["pausa_entre_chamadas_seg"])
        try:
            r = processar(con, itens, catalogo, regras, db.agora_utc(),
                          verificador=getattr(fonte, "verificar", None),
                          max_verificacoes=c.get("verificacoes_por_ciclo", 8))
        finally:
            if hasattr(fonte, "fechar"):
                fonte.fechar()
        if r["verificados"]:
            print(f"  {fonte.nome}: {r['verificados']} produto(s) conferido(s) na pagina da loja")
        print(f"[{fonte.nome}] recebidos {r['recebidos']} | fora do catalogo {r['fora_do_catalogo']} | "
              f"reprovados por reputacao {r['reprovados_reputacao']} | acompanhados {r['acompanhados']} | "
              f"ofertas novas {r['ofertas_novas']}")
    ofertas = _exportar(con, regras, DADOS / "ofertas.json")
    if not ativas:
        print("\nNenhuma loja tem chave configurada ainda. Preencha o arquivo .env (veja .env.example).")
    print(f"\n{len(ofertas)} oferta(s) na fila. Painel: {PAINEL}")
    publicar(regras, env)
    return 0


def publicar(regras, env, avisar_se_desligado=False):
    """Envia o painel para o repositorio publico da pagina. Falha sem derrubar o robo."""
    repo, token = (regras.get("github") or {}).get("repo_painel"), env.get("GITHUB_TOKEN")
    if not (repo and token):
        if avisar_se_desligado:
            print("Falta o GITHUB_TOKEN no arquivo .env (ou 'repo_painel' em regras.json).")
        return False
    if not PAINEL.exists():
        print("Ainda nao existe painel: rode 'rodar.bat coletar' primeiro.")
        return False
    try:
        pasta = (regras.get("github") or {}).get("pasta_painel", "")
        destino = f"{pasta}/index.html" if pasta else "index.html"
        r = github.enviar_arquivo(token, repo, destino, PAINEL.read_bytes(), "Atualiza ofertas")
    except github.ErroGitHub as e:
        print(f"[aviso] painel nao publicado: {e}")
        return False
    dono, nome = repo.split("/")
    print(f"Painel online ({r}): https://{dono}.github.io/{nome}/")
    return True


def cmd_publicar(args):
    """Primeira vez: cria o repositorio publico da pagina e liga o GitHub Pages. Depois, so envia o painel."""
    regras, env = config.carregar_json("regras.json"), config.carregar_env()
    repo, token = (regras.get("github") or {}).get("repo_painel"), env.get("GITHUB_TOKEN")
    if repo and token:
        try:
            for passo in github.preparar_pagina(token, repo, (regras.get("github") or {}).get("pasta_painel", "")):
                print(f"GitHub: {passo}")
        except github.ErroGitHub as e:
            print(f"FALHOU: {e}")
            return 1
    return 0 if publicar(regras, env, True) else 1


def cmd_enviar_codigo(args):
    regras, env = config.carregar_json("regras.json"), config.carregar_env()
    repo, token = (regras.get("github") or {}).get("repo_codigo"), env.get("GITHUB_TOKEN")
    if not (repo and token):
        print("Falta o GITHUB_TOKEN no arquivo .env (ou 'repo_codigo' em regras.json).")
        return 1
    try:
        r = github.enviar_codigo(token, repo, config.RAIZ.parent)
    except github.ErroGitHub as e:
        print(f"FALHOU: {e}")
        return 1
    print(f"Codigo enviado para github.com/{repo}: {r['criado']} novo(s), {r['atualizado']} atualizado(s), {r['igual']} sem mudanca.")
    return 0


def cmd_vigiar(args):
    regras = config.carregar_json("regras.json")
    minutos = regras["coleta"]["intervalo_minutos"]
    print(f"Vigiando a cada {minutos} min. Ctrl+C para parar.")
    while True:
        print(f"\n=== {time.strftime('%d/%m %H:%M')} ===")
        try:
            cmd_coletar(args)
        except Exception as e:  # o robo nao pode morrer por um erro isolado
            print(f"[erro] ciclo falhou: {e!r}")
        time.sleep(minutos * 60)


def cmd_ofertas(args):
    regras = config.carregar_json("regras.json")
    con = db.conectar(DADOS / ("demo_promos.db" if args.demo else "promos.db"))
    ofertas = db.listar_ofertas(con, "nova", args.limite)
    if not ofertas:
        print("Nenhuma oferta nova.")
    for o in ofertas:
        sinais = ", ".join(s["texto"] for s in json.loads(o["sinais"]))
        print(f"\n--- oferta #{o['id']} | {o['desconto_pct']:.0f}% | {sinais}")
        if not o["url_afiliado"]:
            print("    ATENCAO: sem link de afiliado; gere o link antes de postar")
        print(exportar.texto_do_post(o, regras["link_grupo"]))
    return 0


def cmd_adicionar(args):
    catalogo, regras = config.carregar_json("catalogo.json"), config.carregar_json("regras.json")
    preco = para_centavos(args.preco)
    if preco <= 0:
        print("Preco invalido.")
        return 1
    item = Item(loja=args.loja, id_loja=args.url, titulo=args.titulo, preco_cent=preco,
                original_cent=para_centavos(args.de), url=args.url, url_afiliado=args.afiliado or "",
                vendedor=args.vendedor or "", selo="oficial" if args.oficial else "")
    con = db.conectar(DADOS / "promos.db")
    r = processar(con, [item], catalogo, regras, db.agora_utc())
    _exportar(con, regras, DADOS / "ofertas.json")
    if r["fora_do_catalogo"]:
        print("Titulo nao casou com o catalogo (config/catalogo.json). Nada gravado.")
    elif r["reprovados_reputacao"]:
        print("Vendedor reprovado pelas regras de reputacao (use --oficial se for loja oficial). Nada gravado.")
    elif r["ofertas_novas"]:
        print("Preco gravado e oferta registrada. Veja com: rodar.bat ofertas")
    else:
        print("Preco gravado no historico. Nenhum sinal de oferta disparou (ou ela ja estava registrada).")
    return 0


def cmd_testar(args):
    """Uma chamada so. Grava a resposta crua em dados/diagnostico_<loja>.json (sem segredos)."""
    classe = {"shopee": Shopee, "amazon": Amazon, "eshop": Eshop, "mercadolivre": MercadoLivre}[args.loja]
    catalogo, regras = config.carregar_json("catalogo.json"), config.carregar_json("regras.json")
    arquivo = DADOS / f"diagnostico_{args.loja}.json"
    saida = {"loja": args.loja, "busca": args.busca, "quando": db._iso(db.agora_utc())}
    try:
        fonte = _criar_fonte(classe, config.carregar_env(), regras)
        try:
            bruto = fonte.buscar_bruto(args.busca, 1, 10)
            itens = fonte.buscar(args.busca, 1, 10, 0)
        finally:
            if hasattr(fonte, "fechar"):
                fonte.fechar()
        if isinstance(bruto, dict) and "itens" in bruto:      # leitura pelo site: guarda so um resumo
            bruto = {"itens_na_pagina": len(bruto["itens"]), "url": bruto.get("url"), "amostra_html": bruto.get("amostra_html")}
        saida["resposta"] = bruto
        saida["itens_convertidos"] = [i.__dict__ for i in itens]
        saida["ok"] = True
        print(f"OK: a {args.loja} respondeu. {len(itens)} itens com preco na busca '{args.busca}':")
        for i in itens:
            de = f" (de {exportar.reais(i.original_cent)})" if i.original_cent else ""
            print(f"  {exportar.reais(i.preco_cent)}{de} | {i.vendedor or '?'} | {i.titulo[:70]}")
    except (SemCredenciais, ErroDaFonte) as e:
        saida["ok"], saida["erro"] = False, str(e)
        print(f"FALHOU: {e}")
    arquivo.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetalhes gravados em dados/{arquivo.name}")
    return 0 if saida["ok"] else 1


def cmd_entrar(args):
    """Abre o navegador do robo, visivel, para o usuario fazer login uma vez. O login fica no perfil."""
    nav = Navegador(DADOS / "perfil_navegador", visivel=True)
    try:
        nav.ir(ENTRADA)
        print("O navegador do robo abriu no Mercado Livre.")
        print("1. Clique em 'Entre' e faca o login na sua conta, nessa janela.")
        print("2. Quando a pagina inicial aparecer com o seu nome, volte aqui e aperte ENTER.")
        input()
    except (SemCredenciais, ErroDaFonte) as e:
        print(f"FALHOU: {e}")
        return 1
    finally:
        nav.fechar()
    print("Login guardado. Teste com: rodar.bat testar mercadolivre")
    return 0


def cmd_status(args):
    con = db.conectar(DADOS / "promos.db")
    for loja, n in con.execute("SELECT loja, COUNT(*) FROM produtos GROUP BY loja"):
        print(f"{loja}: {n} produtos acompanhados")
    n_precos, desde = con.execute("SELECT COUNT(*), MIN(coletado_em) FROM precos").fetchone()
    print(f"{n_precos} registros de preco" + (f", desde {desde}" if desde else ""))
    for status, n in con.execute("SELECT status, COUNT(*) FROM ofertas GROUP BY status"):
        print(f"ofertas {status}: {n}")
    return 0


def cmd_demo(args):
    """Fluxo completo com dados ficticios, em banco separado (dados/demo_promos.db)."""
    catalogo, regras = config.carregar_json("catalogo.json"), config.carregar_json("regras.json")
    caminho = DADOS / "demo_promos.db"
    con = db.conectar(caminho)
    for tabela in ("ofertas", "precos", "produtos"):
        con.execute(f"DELETE FROM {tabela}")
    amostra = json.loads((config.RAIZ / "tests" / "amostra_shopee.json").read_text(encoding="utf-8"))
    itens = [i for i in (converter(no) for no in amostra["data"]["productOfferV2"]["nodes"]) if i]
    agora = db.agora_utc()
    # 10 dias de historico ficticio, sem desconto, para o sinal de historico aparecer
    for dias_atras in range(10, 0, -1):
        antigos = [Item(**{**i.__dict__, "preco_cent": i.original_cent or i.preco_cent, "original_cent": 0}) for i in itens]
        processar(con, antigos, catalogo, {**regras, "sinais": {**regras["sinais"], "historico_min_dias": 999}},
                  agora - timedelta(days=dias_atras))
    con.execute("DELETE FROM ofertas")
    r = processar(con, itens, catalogo, regras, agora)
    _exportar(con, regras, DADOS / "demo_ofertas.json")
    print("DEMONSTRACAO COM DADOS FICTICIOS (nenhum preco abaixo e real)\n")
    print(f"recebidos {r['recebidos']} | fora do catalogo {r['fora_do_catalogo']} | reprovados por reputacao "
          f"{r['reprovados_reputacao']} | acompanhados {r['acompanhados']} | ofertas {r['ofertas_novas']}")
    args.demo, args.limite = True, 100
    return cmd_ofertas(args)


def main(argv=None):
    for saida in (sys.stdout, sys.stderr):   # emojis no terminal do Windows
        if hasattr(saida, "reconfigure"):
            saida.reconfigure(encoding="utf-8", errors="replace")
    DADOS.mkdir(exist_ok=True)
    p = argparse.ArgumentParser(prog="robo", description="Robo de promocoes do Project N")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("coletar").set_defaults(func=cmd_coletar)
    sub.add_parser("vigiar").set_defaults(func=cmd_vigiar)
    o = sub.add_parser("ofertas")
    o.add_argument("--limite", type=int, default=30)
    o.add_argument("--demo", action="store_true")
    o.set_defaults(func=cmd_ofertas)
    a = sub.add_parser("adicionar")
    a.add_argument("--loja", required=True, choices=["mercadolivre", "amazon", "shopee", "manual"])
    a.add_argument("--titulo", required=True)
    a.add_argument("--preco", required=True, help="preco atual, ex.: 175,17")
    a.add_argument("--de", default="", help="preco 'de' da loja, se houver")
    a.add_argument("--url", required=True)
    a.add_argument("--afiliado", help="link de afiliado ja gerado")
    a.add_argument("--vendedor")
    a.add_argument("--oficial", action="store_true", help="loja oficial / vendido pela propria loja")
    a.set_defaults(func=cmd_adicionar)
    t = sub.add_parser("testar")
    t.add_argument("loja", choices=["amazon", "mercadolivre", "shopee", "eshop"])
    t.add_argument("--busca", default="nintendo switch 2")
    t.set_defaults(func=cmd_testar)
    en = sub.add_parser("entrar")
    en.add_argument("loja", choices=["mercadolivre"])
    en.set_defaults(func=cmd_entrar)
    sub.add_parser("publicar").set_defaults(func=cmd_publicar)
    sub.add_parser("enviar-codigo").set_defaults(func=cmd_enviar_codigo)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("demo").set_defaults(func=cmd_demo)
    args = p.parse_args(argv)
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        print("\nParado.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
