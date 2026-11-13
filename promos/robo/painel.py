"""Gera o painel (docs/index.html): uma pagina unica, sem dependencias, com as ofertas da fila.

Abre direto no navegador (duplo clique) e, se o repositorio tiver GitHub Pages ligado na
pasta /docs, fica online no mesmo formato.
"""
import json

MODELO = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Ofertas - Project N</title>
<style>
:root{--bg:#f6f3f3;--card:#fff;--fg:#1d1517;--muted:#6d6164;--line:#e4dcdd;--red:#c8102e;--ok:#1f7a4d}
@media(prefers-color-scheme:dark){:root{--bg:#151011;--card:#201a1b;--fg:#f3ecec;--muted:#a8999c;--line:#382e30;--red:#ff4d63;--ok:#5fd39a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 "Segoe UI",system-ui,sans-serif;padding:20px 16px 48px}
main{max-width:860px;margin:0 auto}h1{font-size:24px;margin:0}h1 span{color:var(--red)}
.sub{color:var(--muted);margin:2px 0 16px}.bar{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
button{font:600 13px/1 inherit;padding:8px 11px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button[aria-pressed=true],button.go{background:var(--red);border-color:var(--red);color:#fff}
ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;display:grid;grid-template-columns:72px minmax(0,1fr);gap:12px}
li.feita{opacity:.45}img{width:72px;height:72px;object-fit:cover;border-radius:6px;background:var(--line)}
h2{font-size:15px;margin:0;overflow-wrap:anywhere}.p{font-variant-numeric:tabular-nums}.p b{color:var(--red);font-size:16px}
.m{color:var(--muted);font-size:12px;overflow-wrap:anywhere}.a{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
a{color:inherit}.vazio{color:var(--muted);border:1px dashed var(--line);border-radius:10px;padding:24px;text-align:center}
textarea{width:100%;min-height:150px;margin-top:8px;font:12px/1.4 ui-monospace,Consolas,monospace;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px}
</style></head><body><main>
<h1>Ofertas <span>Project N</span></h1>
<p class="sub" id="sub"></p>
<div class="bar" id="lojas"></div>
<ul id="lista"></ul><p class="vazio" id="vazio" hidden>Nenhuma oferta na fila agora.</p>
</main>
<script type="application/json" id="dados">__DADOS__</script>
<script>
(function(){
var D=JSON.parse(document.getElementById('dados').textContent),NOMES={eshop:'eShop',shopee:'Shopee',amazon:'Amazon',mercadolivre:'Mercado Livre',manual:'Manual'};
var filtro='todas',feitas={};try{feitas=JSON.parse(localStorage.getItem('pn_feitas')||'{}')}catch(e){}
function R(n){return 'R$ '+n.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function chave(o){return o.loja+'|'+o.id+'|'+o.detectada_em}
var quando=new Date(D.gerado_em);document.getElementById('sub').textContent=D.total+' oferta(s) na fila. Atualizado em '+quando.toLocaleString('pt-BR')+'.';
function barra(){var b=document.getElementById('lojas');b.textContent='';var cont={todas:D.ofertas.length};D.ofertas.forEach(function(o){cont[o.loja]=(cont[o.loja]||0)+1});
 Object.keys(cont).forEach(function(k){var x=el('button',null,(k==='todas'?'Todas':NOMES[k]||k)+' '+cont[k]);x.setAttribute('aria-pressed',String(k===filtro));x.onclick=function(){filtro=k;barra();lista()};b.appendChild(x)})}
function lista(){var ul=document.getElementById('lista');ul.textContent='';var n=0;
 D.ofertas.forEach(function(o){if(filtro!=='todas'&&o.loja!==filtro)return;n++;var li=el('li',feitas[chave(o)]?'feita':'');
  var im=el('img');im.alt='';im.loading='lazy';if(o.imagem)im.src=o.imagem;li.appendChild(im);var d=el('div');
  d.appendChild(el('h2',null,'['+o.categoria+'] '+o.titulo));
  var p=el('div','p');p.appendChild(el('b',null,R(o.preco)));p.appendChild(document.createTextNode(' '+Math.round(o.desconto_pct)+'% abaixo de '+R(o.referencia)));d.appendChild(p);
  d.appendChild(el('div','m',(NOMES[o.loja]||o.loja)+' · '+o.sinais.map(function(s){return s.texto}).join('; ')+(o.linha_validade?' · '+o.linha_validade:'')+(o.tem_link_afiliado?'':' · SEM LINK DE AFILIADO')));
  var a=el('div','a'),c=el('button','go','Copiar texto'),ta=el('textarea');ta.readOnly=true;ta.hidden=true;ta.value=o.texto;
  c.onclick=function(){function ok(){c.textContent='Copiado';setTimeout(function(){c.textContent='Copiar texto'},1500)}function man(){ta.hidden=false;ta.focus();ta.select()}
   try{navigator.clipboard.writeText(o.texto).then(ok,man)}catch(e){man()}};
  var f=el('button',null,feitas[chave(o)]?'Desfazer':'Já postei');f.onclick=function(){if(feitas[chave(o)])delete feitas[chave(o)];else feitas[chave(o)]=1;try{localStorage.setItem('pn_feitas',JSON.stringify(feitas))}catch(e){}lista()};
  a.appendChild(c);a.appendChild(f);if(o.url){var l=el('a',null,'Abrir na loja');l.href=o.url;l.target='_blank';l.rel='noopener';a.appendChild(l)}
  d.appendChild(a);d.appendChild(ta);li.appendChild(d);ul.appendChild(li)});
 document.getElementById('vazio').hidden=n>0}
barra();lista();
})();
</script></body></html>
"""


def montar(dados):
    """dados = o mesmo dicionario gravado em ofertas.json."""
    bruto = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    return MODELO.replace("__DADOS__", bruto)
