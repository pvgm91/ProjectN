"""Avisos pelo Telegram: um bot seu manda mensagem quando algo quebra (e, se quiser, ofertas e novidades).

Configuracao (uma vez):
  1. No Telegram, fale com @BotFather, mande /newbot e copie o token.
  2. Coloque no .env:  TELEGRAM_BOT_TOKEN=...
  3. Rode: rodar.bat entrar avisos   (mande /start para o bot quando pedir)
O destino fica guardado em dados/telegram_avisos.json. Sem isso, os avisos so aparecem no CMD/log.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.telegram.org/bot{token}/{metodo}"
REPETIR_APOS_H = 6       # o mesmo aviso nao se repete antes disso


class Avisos:
    def __init__(self, env, pasta_dados, enviar=None):
        self.token = "".join((env.get("TELEGRAM_BOT_TOKEN") or "").split())   # tira espacos colados por engano
        self.arq = Path(pasta_dados) / "telegram_avisos.json"
        self._enviar = enviar or self._enviar_http
        self.erro = ""
        self.estado = self._ler()

    def _ler(self):
        try:
            return json.loads(self.arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _guardar(self):
        self.arq.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")

    @property
    def pronto(self):
        return bool(self.token and self.estado.get("chat_id"))

    def _enviar_http(self, metodo, params):
        url = API.format(token=self.token, metodo=metodo)
        req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode())
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except ValueError:
                return {"ok": False, "description": f"HTTP {e.code}"}
        except Exception as e:      # rede fora, token invalido etc.: aviso nunca derruba o robo
            return {"ok": False, "description": str(e)[:200]}

    def descobrir_chat(self):
        """Le a ultima mensagem mandada ao bot e guarda de quem veio. Devolve o nome ou ''."""
        r = self._enviar("getUpdates", {"limit": 20})
        if not r.get("ok"):
            self.erro = r.get("description") or "resposta invalida do Telegram"
            return ""
        msgs = [u.get("message") or u.get("my_chat_member") or {} for u in r.get("result") or []]
        chats = [m.get("chat") for m in msgs if m.get("chat")]
        if not chats:
            return ""
        chat = chats[-1]
        self.estado["chat_id"] = chat["id"]
        self._guardar()
        return chat.get("first_name") or chat.get("title") or str(chat["id"])

    def usuario_do_bot(self):
        """@ do bot (para o link 'Remover' do painel). Guardado depois da primeira consulta."""
        if self.estado.get("bot_usuario") or not self.token:
            return self.estado.get("bot_usuario", "")
        r = self._enviar("getMe", {})
        if r.get("ok"):
            self.estado["bot_usuario"] = (r.get("result") or {}).get("username", "")
            self._guardar()
        return self.estado.get("bot_usuario", "")

    def autorizados(self):
        return {str(self.estado.get("chat_id", ""))} | {str(x) for x in self.estado.get("autorizados", [])}

    def comandos(self):
        """Mensagens novas mandadas ao bot: [(chat_id, texto, nome)]. Marca como lidas."""
        if not self.token:
            return []
        params = {"limit": 100, "timeout": 0}
        if self.estado.get("offset"):
            params["offset"] = self.estado["offset"]
        r = self._enviar("getUpdates", params)
        if not r.get("ok"):
            return []
        saida = []
        for u in r.get("result") or []:
            self.estado["offset"] = u["update_id"] + 1
            m = u.get("message") or {}
            if m.get("text") and m.get("chat"):
                saida.append((str(m["chat"]["id"]), m["text"].strip(), m["chat"].get("first_name") or ""))
        self._guardar()
        return saida

    def responder(self, chat_id, texto):
        self._enviar("sendMessage", {"chat_id": chat_id, "text": texto[:4000], "disable_web_page_preview": "true"})

    def mandar(self, texto):
        if not self.pronto:
            return False
        r = self._enviar("sendMessage", {"chat_id": self.estado["chat_id"], "text": texto[:4000],
                                         "disable_web_page_preview": "true"})
        return bool(r.get("ok"))

    def problema(self, chave, texto):
        """Aviso de falha. A mesma chave so e mandada de novo depois de REPETIR_APOS_H horas."""
        print(f"[aviso] {texto}")
        enviados = self.estado.setdefault("enviados", {})
        if time.time() - enviados.get(chave, 0) < REPETIR_APOS_H * 3600:
            return False
        if self.mandar("⚠️ Robô de promoções do Project N\n\n" + texto):
            enviados[chave] = time.time()
            self._guardar()
            return True
        return False

    def resolvido(self, chave, texto):
        """Se havia aviso aberto para essa chave, avisa que voltou ao normal (uma vez)."""
        enviados = self.estado.get("enviados", {})
        if chave in enviados:
            enviados.pop(chave)
            self._guardar()
            self.mandar("✅ Robô de promoções do Project N\n\n" + texto)
