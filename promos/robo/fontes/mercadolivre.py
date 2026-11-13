"""Mercado Livre. Conector ainda nao implementado.

A busca publica da API do Mercado Livre passou a exigir autenticacao, e o programa de
afiliados gera links pelo portal, sem API documentada. Ate isso ser resolvido, ofertas
do Mercado Livre entram pelo comando manual:  rodar.bat adicionar
"""
from .base import SemCredenciais


class MercadoLivre:
    nome = "mercadolivre"

    def __init__(self, env, enviar=None):
        raise SemCredenciais("Mercado Livre: sem API disponivel; use 'rodar.bat adicionar'")
