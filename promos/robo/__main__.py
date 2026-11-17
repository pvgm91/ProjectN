"""Robo de promocoes do Project N.

Uso (dentro da pasta promos):
    rodar.bat coletar      uma coleta em todas as lojas configuradas
    rodar.bat vigiar       coleta sem parar, no intervalo de regras.json
    rodar.bat ofertas      mostra as ofertas novas, com o texto pronto para o grupo
    rodar.bat adicionar    cadastra uma oferta a mao (ex.: Mercado Livre)
    rodar.bat testar amazon   uma busca de teste (tambem: testar mercadolivre, testar shopee)
    rodar.bat entrar mercadolivre   login unico no navegador do robo
    rodar.bat painel          refaz o painel com o banco atual (sem coletar) e publica
    rodar.bat publicar        envia o painel para a pagina online
    rodar.bat enviar-codigo   envia o codigo para o repositorio privado no GitHub
    rodar.bat status       quantos produtos e precos ja estao no banco
    rodar.bat demo         roda o fluxo inteiro com dados FICTICIOS, sem chaves
"""
import argparse
import json
import os
import sys
import time
from datetime import timedelta

from . import avisos as avisos_mod
from . import config, cupons, db, exportar, github, jogos, links, painel, remover
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


def _sal_do_painel():
    """Sal fixo da senha do painel (criado uma vez). Fixo para o 'lembrar neste navegador' continuar valendo."""
    arq = DADOS / "painel_sal.bin"
    if not arq.exists():
        arq.write_bytes(os.urandom(16))
    return arq.read_bytes()


def _exportar(con, regras, arquivo):
    ofertas = db.listar_ofertas(con, "nova")
    produtos, links_curtos = [], {}
    if arquivo.name == "ofertas.json":
        produtos = exportar.produtos_para_painel(con, db.agora_utc())
        if links.ativo(regras):
            codigos = links.gerar(PAINEL.parent, [{"loja": p["loja"], "id_loja": p["id_loja"], "destino": p["url"],
                                                   "titulo": p["titulo"], "imagem": p["imagem"]} for p in produtos])
            links_curtos = {k: links.base(regras) + c for k, c in codigos.items()}
            for p in produtos:
                p["link_curto"] = links_curtos.get((p["loja"], p["id_loja"]), "")
    dados = exportar.gravar_json(ofertas, arquivo, regras["link_grupo"], db._iso(db.agora_utc()), links_curtos)
    if arquivo.name == "ofertas.json":
        PAINEL.parent.mkdir(exist_ok=True)
        senha = config.carregar_env().get("PAINEL_SENHA", "")
        try:
            lista_cupons = db.listar_cupons(con, db.agora_utc(), _horas_cupons(regras),
                                         (regras.get("cupons_telegram") or {}).get("lojas"))
            bot = avisos_mod.Avisos(config.carregar_env(), DADOS).usuario_do_bot()
            pagina = painel.montar(exportar.dados_do_painel(dados, produtos, regras["link_grupo"], lista_cupons, bot),
                                   senha, _sal_do_painel())
        except painel.ErroCifra as e:
            print(f"[erro] painel NAO atualizado, para nao publicar sem senha: {e}")
            return ofertas
        PAINEL.write_text(pagina, encoding="utf-8")
        painel.copiar_molduras(PAINEL.parent)
    return ofertas


def _criar_fonte(classe, env, regras):
    """Amazon: usa o site (navegador) quando 'amazon_pelo_site' esta ligado; senao, a API."""
    if classe is Amazon and regras.get("amazon_pelo_site"):
        nav = Navegador(DADOS / "perfil_navegador", visivel=regras.get("navegador_visivel", False))
        return AmazonSite(env, nav)
    if classe is MercadoLivre and regras.get("mercadolivre_pelo_site"):
        nav = Navegador(DADOS / "perfil_navegador", visivel=regras.get("navegador_visivel", False))
        return MercadoLivreSite(env, nav)
    if classe is MercadoLivre:
        return MercadoLivre(env, arquivo_token=DADOS / "ml_token.json",
                            lista=config.RAIZ / "config" / "lista_mercadolivre.txt", cache=DADOS / "ml_lista.json",
                            afiliado=regras.get("mercadolivre_afiliado"),
                            lojas=regras.get("mercadolivre_lojas"),
                            por_busca=regras.get("mercadolivre_resultados_por_busca", 50),
                            buscas=(config.carregar_json("catalogo.json").get("buscas", [])
                                    + config.carregar_json("catalogo.json").get("buscas_extras_mercadolivre", [])))
    return classe(env)


def cmd_coletar(args):
    catalogo, regras, env = config.carregar_json("catalogo.json"), config.carregar_json("regras.json"), config.carregar_env()
    con = db.conectar(DADOS / "promos.db")
    c = regras["coleta"]
    ativas = 0
    avisos = avisos_mod.Avisos(env, DADOS)
    _pedidos_de_remocao(con, avisos)
    for classe in FONTES:
        if classe.nome not in regras.get("lojas_ativas", [c.nome for c in FONTES]):
            continue
        try:
            fonte = _criar_fonte(classe, env, regras)
        except SemCredenciais as e:
            print(f"[pulada] {e}")
            continue
        erros_loja = []
        ativas += 1
        buscas_jogos = _buscas_de_jogos(regras, fonte.nome)
        if hasattr(fonte, "buscas_jogos"):          # Mercado Livre: busca os jogos dentro da propria coleta
            fonte.buscas_jogos = buscas_jogos
            fonte.por_jogo = regras.get("resultados_por_jogo", 5)
        itens, falhas = [], 0
        if not getattr(fonte, "por_palavra", True):
            try:
                itens = fonte.coletar()
                print(f"  {fonte.nome}: {len(itens)} itens")
            except ErroDaFonte as e:
                print(f"[erro] {fonte.nome}: {e}")
                erros_loja.append(str(e))
        for palavra in (list(catalogo["buscas"]) + buscas_jogos) if getattr(fonte, "por_palavra", True) else []:
            try:
                paginas = (catalogo.get("paginas_por_busca") or {}).get(palavra, c["paginas_por_busca"])   # buscas que valem mais paginas
                achados = fonte.buscar(palavra, paginas, c["itens_por_pagina"], c["pausa_entre_chamadas_seg"])
            except (ErroDaFonte, SemCredenciais) as e:
                print(f"[erro] {fonte.nome} / '{palavra}': {e}")
                erros_loja.append(str(e))
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
        if getattr(fonte, "falhas", 0):
            print(f"  {fonte.nome}: {fonte.falhas} consulta(s) com erro isolado foram puladas")
        if r["verificados"]:
            print(f"  {fonte.nome}: {r['verificados']} produto(s) conferido(s) na pagina da loja")
        _avisar_loja(avisos, fonte.nome, erros_loja, r["recebidos"])
        print(f"[{fonte.nome}] recebidos {r['recebidos']} | fora do catalogo {r['fora_do_catalogo']} | "
              f"reprovados por reputacao {r['reprovados_reputacao']} | acompanhados {r['acompanhados']} | "
              f"ofertas novas {r['ofertas_novas']}")
    _coletar_cupons(con, regras, env, avisos)
    _coletar_ml_site(con, catalogo, regras, env, avisos)
    ofertas = _exportar(con, regras, DADOS / "ofertas.json")
    if not ativas:
        print("\nNenhuma loja tem chave configurada ainda. Preencha o arquivo .env (veja .env.example).")
    print(f"\n{len(ofertas)} oferta(s) na fila. Painel: {PAINEL}")
    if not publicar(regras, env) and env.get("GITHUB_TOKEN"):
        avisos.problema("publicar", "O painel não foi publicado no GitHub nesta coleta. Veja o log (dados\\log.txt).")
    else:
        avisos.resolvido("publicar", "O painel voltou a ser publicado.")
    return 0


LOGIN_ML_SITE = "rodar.bat entrar mercadolivre-site"


def _navegador_ml(regras, visivel):
    """Navegador do Mercado Livre: perfil proprio (dados/perfil_mercadolivre), no Chrome por padrao.
    Separado do perfil da Amazon para um login nao atrapalhar o outro."""
    canal = (regras.get("mercadolivre_site") or {}).get("navegador", "chrome")
    canais = {"chrome": ("chrome",), "edge": ("msedge",)}.get(canal, ("chrome",))      # sem trocar de navegador escondido
    return Navegador(DADOS / "perfil_mercadolivre", visivel=visivel, canais=canais)


def _coletar_ml_site(con, catalogo, regras, env, avisos):
    """Mercado Livre pelo site, com o login do robo: vitrine das lojas preferidas e conferencia de cupons."""
    cfg = regras.get("mercadolivre_site") or {}
    if not cfg.get("ativo") or "mercadolivre" not in regras.get("lojas_ativas", ["mercadolivre"]):
        return
    nav = _navegador_ml(regras, regras.get("navegador_visivel", False))
    fonte = MercadoLivreSite(env, nav, lojas=regras.get("mercadolivre_lojas"), afiliado=regras.get("mercadolivre_afiliado"),
                             so_lojas=cfg.get("so_lojas", True))
    erros, itens = [], []
    try:
        for palavra in cfg.get("buscas", []):
            try:
                achados = fonte.buscar(palavra, cfg.get("paginas", 2))
                print(f"  mercadolivre (site) / '{palavra}': {len(achados)} itens")
                itens += achados
            except (ErroDaFonte, SemCredenciais) as e:
                print(f"[erro] mercadolivre (site) / '{palavra}': {e}")
                erros.append(str(e))
                if fonte.bloqueada or isinstance(e, SemCredenciais):
                    break
        if itens:
            r = processar(con, itens, catalogo, regras, db.agora_utc())
            print(f"[mercadolivre site] recebidos {r['recebidos']} | fora do catalogo {r['fora_do_catalogo']} | "
                  f"acompanhados {r['acompanhados']} | ofertas novas {r['ofertas_novas']}")
        if cfg.get("conferir_cupons", True) and not fonte.bloqueada:
            try:
                _conferir_cupons_ml(con, fonte)
            except ErroDaFonte as e:
                print(f"[erro] cupons do Mercado Livre: {e}")
                erros.append(str(e))
    finally:
        fonte.fechar()
    if any("login" in e.lower() for e in erros):
        avisos.problema("mercadolivre-site", "O Mercado Livre pediu login no navegador do robô (vitrine da Gamer Hut e "
                                             f"conferência de cupons pararam). No CMD: {LOGIN_ML_SITE}")
    elif erros:
        avisos.problema("mercadolivre-site", f"Erro ao ler o site do Mercado Livre: {erros[0][:300]}")
    else:
        avisos.resolvido("mercadolivre-site", "A leitura do site do Mercado Livre voltou ao normal.")


def _conferir_cupons_ml(con, fonte):
    """Procura na pagina de cupons da conta os cupons de Mercado Livre vistos no Telegram."""
    agora = db.agora_utc()
    codigos = sorted({c["codigo"] for c in db.listar_cupons(con, agora, 48, ["mercadolivre"]) if c["loja"] == "mercadolivre"})
    if not codigos:
        return
    dados = fonte.conferir_cupons(codigos)
    (DADOS / "diagnostico_ml_cupons.txt").write_text(
        f"{dados.get('url')}\nprocurados: {', '.join(codigos)}\nachados: {json.dumps(dados.get('achados'), ensure_ascii=False)}\n\n"
        f"{dados.get('texto', '')}", encoding="utf-8")
    for codigo, texto in (dados.get("achados") or {}).items():
        db.confirmar_cupom(con, codigo, "mercadolivre", texto, cupons._regras(texto, agora), agora)
    con.commit()
    print(f"[cupons] {len(dados.get('achados') or {})} de {len(codigos)} cupom(ns) do Mercado Livre confirmado(s) na página de cupons")


def cmd_vitrine(args):
    """So a parte do site do Mercado Livre (vitrine das lojas preferidas + cupons), depois atualiza o painel."""
    catalogo, regras, env = config.carregar_json("catalogo.json"), config.carregar_json("regras.json"), config.carregar_env()
    regras = dict(regras, mercadolivre_site=dict(regras.get("mercadolivre_site") or {}, ativo=True))
    con = db.conectar(DADOS / "promos.db")
    _coletar_ml_site(con, catalogo, regras, env, avisos_mod.Avisos(env, DADOS))
    _exportar(con, regras, DADOS / "ofertas.json")
    publicar(regras, env)
    return 0


def _entrar_ml_site():
    """Abre o navegador do robo no Mercado Livre para o login ser feito UMA vez (a pessoa digita a senha)."""
    import re as _re
    nav = _navegador_ml(config.carregar_json("regras.json"), True)
    try:
        nav.ir("https://www.mercadolivre.com.br/cupons")
        print("Abriu uma janela do navegador do robo no Mercado Livre.")
        print("Entre na sua conta NELA (voce mesmo digita e-mail, senha e codigo).")
        print("Se o robo estiver rodando agora pelo agendador, espere ele terminar antes.")
        input("Quando a pagina de cupons aparecer, aperte ENTER aqui...")
        url = nav.pagina.url
    finally:
        nav.fechar()
    if _re.search(r"account-verification|/login|/registration", url):
        print("Ainda nao entrou na conta. Rode de novo e faca o login na janela que abrir.")
        return 1
    print("Pronto: login guardado no navegador do robo. Teste com: rodar.bat vitrine")
    return 0


def _buscas_de_jogos(regras, loja):
    """Proximos jogos da fila de config/jogos.txt para esta loja (rodizio entre as coletas)."""
    quantos = (regras.get("jogos_por_ciclo") or {}).get(loja, 0)
    lista = jogos.ler_jogos(config.RAIZ / "config" / "jogos.txt")
    escolhidos = jogos.rodizio(lista, quantos, DADOS / "rodizio_jogos.json", loja)
    if escolhidos:
        print(f"  {loja}: {len(escolhidos)} jogo(s) da lista nesta coleta (de {len(lista)})")
    return [jogos.consulta(p, t) for p, t in escolhidos]


def _pedidos_de_remocao(con, avisos):
    """Aplica os 'Remover'/'Voltar' mandados pelo painel via bot do Telegram."""
    try:
        n = remover.processar(con, avisos, db.agora_utc())
    except Exception as e:          # nunca derruba a coleta
        print(f"[erro] pedidos de remocao: {e}")
        return
    if n:
        print(f"[painel] {n} produto(s) removido(s)/devolvido(s) pelo Telegram")


def cmd_autorizar(args):
    """Deixa outra pessoa (ex.: quem divide o grupo com voce) usar o 'Remover' do painel pelo bot."""
    avisos = avisos_mod.Avisos(config.carregar_env(), DADOS)
    lista = [str(x) for x in avisos.estado.get("autorizados", [])]
    if str(args.chat) not in lista:
        lista.append(str(args.chat))
    avisos.estado["autorizados"] = lista
    avisos._guardar()
    avisos.responder(args.chat, "✅ Pronto: agora você pode remover produtos do painel do Project N por aqui.")
    print(f"Autorizado: {args.chat}")
    return 0


def _horas_cupons(regras):
    """Quantas horas um cupom fica no painel depois de postado no Telegram (padrao 3)."""
    return (regras.get("cupons_telegram") or {}).get("horas_no_painel", 3)


def _coletar_cupons(con, regras, env, avisos, horas=None):
    cfg = regras.get("cupons_telegram") or {}
    canais = [c for c in cfg.get("canais", []) if c.strip()]
    if not canais:
        return
    from datetime import timedelta
    desde = db.agora_utc() - timedelta(hours=horas or cfg.get("horas_para_tras", 6))
    try:
        mensagens = cupons.ler(env, DADOS / "telegram.session", canais, desde, cfg.get("mensagens_por_canal", 200))
    except cupons.SemTelegram as e:
        avisos.problema("telegram", f"Não consegui ler os cupons do Telegram: {e}")
        return
    except Exception as e:          # rede, canal privado etc.: nao derruba a coleta
        avisos.problema("telegram", f"Erro ao ler os cupons do Telegram: {str(e)[:300]}")
        return
    achados = 0
    for canal, quando, texto in mensagens:
        for c in cupons.extrair(texto, quando):
            if not c["loja"]:          # grupo de uma loja so: a loja vem do grupo
                c["loja"] = (cfg.get("loja_do_canal") or {}).get(canal, "")
            if cfg.get("lojas") and c["loja"] and c["loja"] not in cfg["lojas"]:
                continue        # loja que nao interessa (ex.: KaBuM!, Magalu)
            db.salvar_cupom(con, c, canal, quando)
            achados += 1
    con.commit()
    avisos.resolvido("telegram", "A leitura de cupons do Telegram voltou ao normal.")
    print(f"[cupons] {len(mensagens)} mensagem(ns) lida(s), {achados} cupom(ns) encontrado(s)")
    return achados


NOMES_LOJAS = {"amazon": "Amazon", "mercadolivre": "Mercado Livre", "shopee": "Shopee", "eshop": "Nintendo eShop"}


def _avisar_loja(avisos, loja, erros, recebidos):
    """Transforma o resultado de uma loja em aviso: bloqueio, acesso expirado ou loja sem produto nenhum."""
    nome, texto = NOMES_LOJAS.get(loja, loja), " ".join(erros).lower()
    if "captcha" in texto or "verificacao" in texto:
        avisos.problema(f"{loja}-captcha", f"A {nome} pediu verificação (CAPTCHA). A coleta dela parou neste ciclo e tenta de novo na próxima hora.")
    elif "entrar mercadolivre" in texto or "expirou" in texto or "recusou" in texto or "credenciais" in texto:
        avisos.problema(f"{loja}-acesso", f"O acesso ao {nome} foi recusado ou expirou. No CMD: rodar.bat entrar {loja}")
    elif recebidos == 0:
        avisos.problema(f"{loja}-vazio", f"A coleta da {nome} não trouxe nenhum produto. " +
                        (f"Erro: {erros[0][:300]}" if erros else "Pode ser mudança no site ou bloqueio."))
    else:
        for k in ("captcha", "acesso", "vazio"):
            avisos.resolvido(f"{loja}-{k}", f"A coleta da {nome} voltou ao normal ({recebidos} produtos).")


def publicar(regras, env, avisar_se_desligado=False):
    """Envia painel, links curtos e dominio para o GitHub, num commit so. Falha sem derrubar o robo."""
    repo, token = (regras.get("github") or {}).get("repo_painel"), env.get("GITHUB_TOKEN")
    if not (repo and token):
        if avisar_se_desligado:
            print("Falta o GITHUB_TOKEN no arquivo .env (ou 'repo_painel' em regras.json).")
        return False
    if not PAINEL.exists():
        print("Ainda nao existe painel: rode 'rodar.bat coletar' primeiro.")
        return False
    pasta = (regras.get("github") or {}).get("pasta_painel", "")
    prefixo = f"{pasta}/" if pasta else ""
    dominio = ((regras.get("links_curtos") or {}).get("dominio") or "").strip()
    textos = {prefixo + "index.html": PAINEL.read_text(encoding="utf-8")}
    if env.get("PAINEL_SENHA") and '"cifrado": 1' not in textos[prefixo + "index.html"]:
        print("[aviso] painel nao publicado: a senha esta no .env, mas o painel local ainda esta sem protecao. Rode 'rodar.bat painel'.")
        return False
    for pag in sorted((PAINEL.parent / "l").glob("*.html")):
        textos[prefixo + "l/" + pag.name] = pag.read_text(encoding="utf-8")
    if dominio:
        textos[prefixo + "CNAME"] = dominio + "\n"
    try:
        r = github.enviar_lote(token, repo, textos, "Atualiza ofertas")
        for moldura in sorted((PAINEL.parent / "arte").glob("*.png")):      # so envia se mudou
            github.enviar_arquivo(token, repo, prefixo + "arte/" + moldura.name, moldura.read_bytes(), "Atualiza moldura da arte")
        if dominio:
            github.definir_dominio(token, repo, dominio)
    except github.ErroGitHub as e:
        print(f"[aviso] painel nao publicado: {e}")
        return False
    dono, nome = repo.split("/")
    endereco = f"https://{dominio}/" if dominio else f"https://{dono}.github.io/{nome}/"
    print(f"Painel online ({r} arquivo(s) atualizado(s)): {endereco}")
    return True


def cmd_painel(args):
    """Refaz o painel com o banco atual (sem coletar) e publica."""
    regras = config.carregar_json("regras.json")
    con = db.conectar(DADOS / "promos.db")
    _pedidos_de_remocao(con, avisos_mod.Avisos(config.carregar_env(), DADOS))
    ofertas = _exportar(con, regras, DADOS / "ofertas.json")
    print(f"Painel refeito: {len(ofertas)} oferta(s). {PAINEL}")
    publicar(regras, config.carregar_env())
    return 0


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
            saida["resposta"] = bruto      # guardado ja, para o diagnostico sobreviver a um erro na conversao
            if hasattr(fonte, "nav"):
                fonte.nav.foto(DADOS / f"diagnostico_{args.loja}.png")
            itens = fonte.buscar(args.busca, 1, 10, 0)
        finally:
            if hasattr(fonte, "fechar"):
                fonte.fechar()
        if isinstance(bruto, dict) and "itens" in bruto:      # leitura pelo site: guarda so um resumo
            bruto = {"itens_na_pagina": len(bruto["itens"]), **{k: v for k, v in bruto.items() if k != "itens"}}
        saida["resposta"] = bruto
        saida["itens_convertidos"] = [i.__dict__ for i in itens]
        saida["ok"] = bool(itens)
        if getattr(fonte, "tipo_token", ""):
            print(f"Acesso da {fonte.tipo_token}.")
        if getattr(fonte, "ignorados", None):
            print(f"{len(fonte.ignorados)} link(s) da lista ignorado(s): so links de produto de catalogo (.../p/MLB...) "
                  f"podem ser lidos pela API. Abra o anuncio e use o link que tem /p/MLB.")
        print(f"OK: a {args.loja} respondeu. {len(itens)} itens com preco na busca '{args.busca}':" if itens
              else f"FALHOU: a {args.loja} respondeu, mas nenhum produto foi lido na busca '{args.busca}'.")
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
    """Autorizacoes de uma vez so: Mercado Livre (conta), avisos (bot do Telegram) e telegram (leitura de cupons)."""
    if args.loja == "avisos":
        return _entrar_avisos()
    if args.loja == "telegram":
        return _entrar_telegram()
    if args.loja == "mercadolivre-site":
        return _entrar_ml_site()
    import webbrowser
    try:
        fonte = MercadoLivre(config.carregar_env(), arquivo_token=DADOS / "ml_token.json")
    except SemCredenciais as e:
        print(f"FALHOU: {e}")
        return 1
    url = fonte.url_autorizacao()
    print("1. Vai abrir o Mercado Livre pedindo para autorizar a sua aplicacao. Entre na sua conta e clique em Permitir.")
    print("2. Depois disso o navegador vai para o site do Project N. Copie o endereco INTEIRO da barra")
    print("   (ele tem '?code=TG-...') e cole aqui embaixo. O codigo vale poucos minutos.\n")
    print(url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    colado = input("Endereco: ")
    try:
        conta = fonte.autorizar(colado)
    except ErroDaFonte as e:
        print(f"FALHOU: {e}")
        return 1
    print(f"Pronto: acesso da conta {conta.get('user_id') or ''} guardado em dados/ml_token.json.")
    print("Teste com: rodar.bat testar mercadolivre")
    return 0


def _entrar_avisos():
    env = config.carregar_env()
    if not env.get("TELEGRAM_BOT_TOKEN"):
        print("Falta o TELEGRAM_BOT_TOKEN no .env. No Telegram, fale com @BotFather, mande /newbot e copie o token.")
        return 1
    av = avisos_mod.Avisos(env, DADOS)
    input("Abra o seu bot no Telegram, mande /start para ele e depois aperte ENTER aqui...")
    nome = av.descobrir_chat()
    if not nome and av.erro:
        print(f"FALHOU: o Telegram recusou o token ({av.erro}). Confira o TELEGRAM_BOT_TOKEN no .env, "
              "copiado inteiro do @BotFather, sem espacos.")
        return 1
    if not nome:
        print("FALHOU: o bot nao recebeu nenhuma mensagem. Mande /start para ele e rode de novo.")
        return 1
    ok = av.mandar("✅ Avisos do robô de promoções do Project N ligados. Vou te chamar aqui se a coleta tiver problema.")
    print(f"Pronto: avisos vao para {nome}." if ok else "FALHOU: nao consegui mandar a mensagem de teste.")
    return 0 if ok else 1


def _entrar_telegram():
    env = config.carregar_env()
    try:
        cli = cupons.cliente(env, DADOS / "telegram.session")
    except cupons.SemTelegram as e:
        print(f"FALHOU: {e}")
        return 1
    print("O Telegram vai pedir o seu numero (com +55) e o codigo que chega no app. Se tiver senha em duas etapas, ela tambem.")
    cli.start()
    print("\nPronto: conta do Telegram conectada. Grupos e canais que voce segue (use estes nomes em regras.json):")
    for d in cli.iter_dialogs(limit=80):
        if d.is_group or d.is_channel:
            print(f"  - {d.name}")
    cli.disconnect()
    return 0


def cmd_cupons(args):
    """Le so os cupons do Telegram (sem coletar lojas), mostra o que achou e atualiza o painel."""
    regras, env = config.carregar_json("regras.json"), config.carregar_env()
    con = db.conectar(DADOS / "promos.db")
    avisos = avisos_mod.Avisos(env, DADOS)
    _coletar_cupons(con, regras, env, avisos, args.horas)
    lista = db.listar_cupons(con, db.agora_utc(), _horas_cupons(regras),
                                         (regras.get("cupons_telegram") or {}).get("lojas"))
    for c in lista[:30]:
        regra = f"{c['desconto_pct']:.0f}% off" if c["desconto_pct"] else (exportar.reais(c["desconto_cent"]) + " off" if c["desconto_cent"] else "?")
        print(f"  {c['codigo']:<18} {c['loja'] or '(loja?)':<13} {regra:<14} {c['origem']}")
    if not lista:
        print("Nenhum cupom valido encontrado nas mensagens lidas.")
    _exportar(con, regras, DADOS / "ofertas.json")
    publicar(regras, env)
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
    en.add_argument("loja", choices=["mercadolivre", "mercadolivre-site", "avisos", "telegram"])
    en.set_defaults(func=cmd_entrar)
    sub.add_parser("publicar").set_defaults(func=cmd_publicar)
    sub.add_parser("painel").set_defaults(func=cmd_painel)
    sub.add_parser("enviar-codigo").set_defaults(func=cmd_enviar_codigo)
    cp = sub.add_parser("cupons")
    cp.add_argument("--horas", type=int, default=48, help="quantas horas de mensagens ler (padrao 48)")
    cp.set_defaults(func=cmd_cupons)
    sub.add_parser("vitrine", help="le a vitrine das lojas preferidas e confere cupons no site do Mercado Livre").set_defaults(func=cmd_vitrine)
    a = sub.add_parser("autorizar", help="autoriza outra conta do Telegram a remover produtos pelo painel")
    a.add_argument("chat")
    a.set_defaults(func=cmd_autorizar)
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
