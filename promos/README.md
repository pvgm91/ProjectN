# Robô de promoções do Project N

Acompanha preços de produtos do universo Nintendo, guarda o histórico e aponta o que é oferta, já com o texto pronto para o grupo.

Esta é a etapa 1: coleta, histórico e detecção. Painel de aprovação, artes, cupons e publicação vêm nas próximas.

## Como usar

Precisa do Python 3.9 ou mais novo. Para a Amazon pelo site, rode `instalar.bat` uma vez (instala o Playwright; o navegador usado é o Edge do Windows).

Dê dois cliques ou rode no terminal, dentro da pasta `promos`:

| Comando | O que faz |
|---|---|
| `rodar.bat demo` | Roda o fluxo inteiro com dados fictícios, sem chave nenhuma |
| `rodar.bat coletar` | Uma coleta nas três lojas (Amazon, Mercado Livre, Shopee); pula a que ainda não estiver pronta |
| `vigiar.bat` | Coleta sem parar (a cada 30 min); deixe a janela aberta |
| `rodar.bat ofertas` | Mostra as ofertas novas com o texto pronto para colar no grupo |
| `rodar.bat testar amazon` | Uma única chamada à loja, para conferir a chave (também `testar shopee`) |
| `abrir_painel.bat` | Abre o painel de ofertas (`docs\index.html`), regerado a cada coleta |
| `rodar.bat status` | Quantos produtos e preços já estão no banco |
| `rodar.bat adicionar ...` | Cadastra uma oferta à mão (hoje, o caminho para o Mercado Livre) |

Exemplo de cadastro manual:

```
rodar.bat adicionar --loja mercadolivre --titulo "Sonic X Shadow Generations - Nintendo Switch 2" --preco 175,17 --de 227,38 --url https://... --afiliado https://... --oficial
```

## Chaves das lojas

Copie `.env.example` para `.env` e preencha. O `.env` fica só no PC; o `.gitignore` impede que ele vá para o GitHub.

| Loja | Situação | Onde pegar a chave |
|---|---|---|
| Nintendo eShop | Desligada (ligue em `lojas_ativas`, no `regras.json`). Funciona sem chave: lê a página pública de ofertas da loja (cerca de 100 destaques). Sem afiliado | — |
| Shopee | Conector pronto, ainda não testado com chave real | affiliate.shopee.com.br, seção Open API |
| Amazon | **Pelo site, sem API** (`amazon_pelo_site: true`): o robô abre a busca da amazon.com.br num navegador, acompanha os preços e, quando há sinal de oferta, confere preço e vendedor na página do produto. Só vira oferta o que é vendido pela Amazon. Se aparecer CAPTCHA, a coleta da Amazon para naquele ciclo. Precisa do `instalar.bat` uma vez. A Creators API fica pronta para quando a conta for elegível (`amazon_pelo_site: false`) | — |
| Mercado Livre | **Pelo site, sem API** (`mercadolivre_pelo_site: true`): exige um login único no navegador do robô (`rodar.bat entrar mercadolivre`). Só entra anúncio de loja oficial. O link de afiliado continua saindo do portal | — |

## Como uma oferta é detectada

Um item só é acompanhado se passar em dois filtros:

1. **Catálogo** (`config/catalogo.json`): o título precisa casar com um grupo de termos e não ter termo bloqueado.
2. **Reputação** (`config/regras.json`): selo de loja oficial ou indicada, nota mínima e vendas mínimas, por loja.

Depois, quatro sinais são testados. Qualquer um deles gera uma oferta:

| Sinal | Regra | Funciona desde |
|---|---|---|
| `desconto_loja` | preço atual ≥ 15% abaixo do preço "de" da loja | primeiro dia |
| `preco_sugerido` | preço atual ≥ 15% abaixo do preço cheio cadastrado em `produtos` | primeiro dia, para produtos cadastrados |
| `entre_lojas` | preço atual ≥ 10% abaixo da mediana do mesmo produto nas outras lojas (últimas 24h) | quando houver duas lojas coletando o produto |
| `historico` | preço atual ≥ 10% abaixo da mediana dos menores preços diários anteriores | após 7 dias de histórico |

Fórmula de todos: `pct = (referência − preço) / referência × 100`. A oferta guarda quais sinais dispararam, então dá para ver quando o desconto da loja não é confirmado pelo histórico.

Outras regras:

- Preço abaixo de R$ 30 não vira oferta.
- Na eShop, jogo com preço cheio abaixo de R$ 60 fica de fora (corta os jogos de baixa qualidade).
- A mesma oferta não se repete por 48 horas, a menos que o preço caia mais 3%.
- Preço igual só é regravado no histórico a cada 6 horas.

Todos os limites estão em `config/regras.json`.

## Pastas

```
promos/
  config/     catálogo e regras (editáveis)
  robo/       código
    fontes/   um conector por loja
  tests/      testes automáticos e amostra fictícia
  dados/      banco local (promos.db) e ofertas.json
```

Testes: `py -3 -m unittest discover -s tests -v`

## Painel

Cada coleta regera `docs/index.html`, uma página única com as ofertas da fila, botão de copiar o texto e marcação "Já postei" (guardada só no navegador de quem marcou). Abra com `abrir_painel.bat`.

Para ter o painel online, o repositório `pvgm91/ProjectN` precisa ser público. O robô envia o painel para a pasta `docs` a cada coleta, usando o `GITHUB_TOKEN` do `.env`, e o GitHub Pages serve essa pasta em https://pvgm91.github.io/ProjectN/.

Primeira vez: `rodar.bat enviar-codigo` (manda o projeto) e depois `rodar.bat publicar` (liga o GitHub Pages e envia o painel). O `.env`, o banco e o perfil do navegador nunca são enviados.

## Rodar de hora em hora

`agendar.bat` cria uma tarefa no Agendador do Windows que roda a coleta a cada hora, sem precisar de janela aberta. O resultado de cada rodada fica em `dados\log.txt`. `desagendar.bat` remove a tarefa.
