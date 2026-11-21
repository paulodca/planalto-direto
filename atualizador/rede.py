"""Acesso de rede do atualizador: ritmo, cache, falhas, backoff e parada.

Este é o ÚNICO módulo do projeto que faz requisição HTTP. A base do Planalto
vem de ``pd.config.ler_config()["PLANALTO_BASE"]`` (ponto único) e é passada ao
``Cliente`` por quem o cria.
"""
from __future__ import annotations

import datetime
import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PlanaltoDireto/1.0 (+https://paulodca.github.io/planalto-direto/)"
CABECALHOS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "pt-BR,pt;q=0.9"}
INTERVALO_S = 1.0
JITTER_S = (0.0, 0.6)
BACKOFF_S = (5, 10, 20)
FALHAS_MAX = 3
TIMEOUT_S = 30



class Parada(Exception):
    """Execução interrompida: 3 falhas seguidas ou teto de requisições."""

    def __init__(self, url: str, motivo: str):
        super().__init__(f"parada em {url}: {motivo}")
        self.url = url
        self.motivo = motivo


@dataclass
class Resposta:
    raw: bytes
    url_pedida: str
    url_final: str
    status: int
    do_cache: bool = False


class _Falha(Exception):
    """Tentativa falha (uso interno)."""


def corpo_valido(raw: bytes, bytes_anterior: int | None) -> tuple[bool, str]:
    """Corpo inválido: TSPD, sem </html> ou menor que 70% do tamanho anterior.

    ``bytes_anterior`` tem de ser o tamanho do corpo CRU da leitura anterior do próprio
    atualizador (``Cliente.bytes_anterior_cru``), nunca o de uma cópia reformatada.
    ``None`` = sem leitura anterior: a regra dos 70% não se aplica; as outras, sempre.
    """
    if b"TSPD" in raw:
        return False, "tspd"
    if b"</html>" not in raw.lower():
        return False, "sem </html>"
    if bytes_anterior and len(raw) < 0.7 * bytes_anterior:
        return False, "menor que 70%"
    return True, ""


def caminho_local(raiz: Path, caminho_rel: str, base: str) -> Path:
    """``<raiz>/<host>/<caminho da base>/<caminho em minúsculas>``.

    Com a base atual: ``<raiz>/www.planalto.gov.br/ccivil_03/<caminho>``.
    """
    b = urlsplit(base)
    pref = [b.netloc.lower()] + [p for p in b.path.lower().split("/") if p]
    partes = [p for p in caminho_rel.replace("\\", "/").lower().split("/") if p not in ("", ".", "..")]
    return Path(raiz, *pref, *partes)


def _gravar_atomico(destino: Path, dados: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(dados)
    os.replace(tmp, destino)


class Cliente:
    def __init__(self, base: str, estado: Path, cache_horas: float, max_req: int, offline_raiz: Path | None,
                 *, relogio=time.monotonic, dormir=time.sleep, agora=time.time,
                 aleatorio=random.uniform, abrir=None):
        if not base.endswith("/"):
            base += "/"
        self.base = base
        self.estado = Path(estado)
        self.cache_horas = float(cache_horas)
        self.max_req = int(max_req)
        self.offline_raiz = Path(offline_raiz) if offline_raiz else None
        self._relogio = relogio
        self._dormir = dormir
        self._agora = agora
        self._aleatorio = aleatorio
        self._abrir = abrir or self._abrir_urllib
        self._ultimo: float | None = None
        self.falhas_seguidas = 0
        self.requisicoes = 0      # requisições de rede feitas
        self.falhas = 0           # tentativas falhas no total
        self.eventos: list[dict] = []

    # ---------------------------------------------------------------- log
    def _registrar(self, **ev) -> None:
        ev["quando"] = datetime.datetime.fromtimestamp(self._agora(), datetime.timezone.utc).isoformat(timespec="seconds")
        self.eventos.append(ev)
        try:
            self.estado.mkdir(parents=True, exist_ok=True)
            with open(self.estado / "log.jsonl", "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            pass

    # -------------------------------------------------------------- cache
    def _arquivo_cache(self, caminho_rel: str) -> Path:
        return caminho_local(self.estado / "cache", caminho_rel, self.base)

    def bytes_anterior_cru(self, caminho_rel: str) -> int | None:
        """Tamanho do corpo cru da leitura anterior deste atualizador (``estado/cache``), ou ``None``.

        Só corpo válido entra no cache, e a gravação é atômica; por isso o arquivo é a
        última leitura boa, byte a byte. Tem de ser lido ANTES de ``obter``, que o sobrescreve.
        """
        try:
            n = self._arquivo_cache(caminho_rel).stat().st_size
        except OSError:
            return None
        return n or None

    def _do_cache(self, caminho_rel: str) -> bytes | None:
        arq = self._arquivo_cache(caminho_rel)
        try:
            idade = self._agora() - arq.stat().st_mtime
        except OSError:
            return None
        if idade < self.cache_horas * 3600:
            return arq.read_bytes()
        return None

    # ---------------------------------------------------------------- rede
    def _esperar_vez(self) -> None:
        if self._ultimo is not None:
            alvo = self._ultimo + INTERVALO_S + self._aleatorio(*JITTER_S)
            falta = alvo - self._relogio()
            if falta > 0:
                self._dormir(falta)
        self._ultimo = self._relogio()

    @staticmethod
    def _abrir_urllib(url: str):
        """Devolve (status, corpo, url_final). 404 e outros códigos voltam como status."""
        pedido = urllib.request.Request(url, headers=CABECALHOS)
        abridor = urllib.request.build_opener()  # inclui o HTTPRedirectHandler padrão
        try:
            with abridor.open(pedido, timeout=TIMEOUT_S) as r:
                return r.status, r.read(), r.geturl()
        except urllib.error.HTTPError as e:
            return e.code, b"", e.geturl() or url

    def _tentar(self, url: str, caminho_rel: str):
        """Uma tentativa: devolve (status, corpo, url_final) ou levanta _Falha."""
        if self.offline_raiz is not None:
            arq = caminho_local(self.offline_raiz, caminho_rel, self.base)
            if not arq.is_file():
                return 404, b"", url
            return 200, arq.read_bytes(), url
        if self.requisicoes >= self.max_req:
            raise Parada(url, f"teto de {self.max_req} requisições atingido")
        self._esperar_vez()
        self.requisicoes += 1
        try:
            return self._abrir(url)
        except Exception as e:  # rede, timeout, protocolo
            raise _Falha(f"{type(e).__name__}: {e}") from None

    def obter(self, caminho_rel: str, bytes_anterior: int | None) -> Resposta | None:
        """Lê ``base + caminho_rel``. ``None`` = 404. Levanta ``Parada``."""
        url = self.base + caminho_rel.lstrip("/")
        if self.offline_raiz is None:
            em_cache = self._do_cache(caminho_rel)
            if em_cache is not None:
                self._registrar(url_pedida=url, url_final=url, status=200, bytes=len(em_cache), resultado="cache")
                return Resposta(em_cache, url, url, 200, do_cache=True)
        while True:
            try:
                status, raw, url_final = self._tentar(url, caminho_rel)
                if status == 404:
                    self._registrar(url_pedida=url, url_final=url_final, status=404, bytes=0, resultado="404")
                    return None
                if status != 200:
                    raise _Falha(f"HTTP {status}")
                ok, motivo = corpo_valido(raw, bytes_anterior)
                if not ok:
                    raise _Falha(motivo)
            except _Falha as f:
                self.falhas += 1
                self.falhas_seguidas += 1
                motivo = str(f)
                self._registrar(url_pedida=url, url_final=url, status=None, bytes=None, resultado="falha", motivo=motivo)
                if self.falhas_seguidas >= FALHAS_MAX:
                    raise Parada(url, motivo) from None
                if self.offline_raiz is None:
                    self._dormir(BACKOFF_S[min(self.falhas_seguidas - 1, 2)])
                continue
            self.falhas_seguidas = 0
            self._registrar(url_pedida=url, url_final=url_final, status=200, bytes=len(raw), resultado="ok")
            if self.offline_raiz is None:
                _gravar_atomico(self._arquivo_cache(caminho_rel), raw)
            return Resposta(raw, url, url_final, 200)
