"""Servidor estático de teste que imita o GitHub Pages (SPEC §14.3), só stdlib.

Modo site (padrão): serve --raiz sob --prefixo; diretório -> index.html; diretório sem barra -> 301;
inexistente -> <raiz>/404.html com status 404; nenhuma outra regra. Monta testes/ em /__testes__/.
Modo --legado: serve páginas do Planalto guardadas localmente (pasta passada em --raiz, a que contém
ccivil_03/); caminho com maiúscula -> 301 para minúsculas; .htm/.html com charset windows-1252 (ou utf-8,
se declarado nos 4.096 primeiros bytes); ?sem-charset=1 manda só text/html.
Escuta só em 127.0.0.1 e imprime a porta na 1ª linha do stdout.
"""
import sys, pathlib
RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import argparse
import http.server
import posixpath
import re
import urllib.parse

TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".xml": "application/xml",
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
}
META_CHARSET_RE = re.compile(rb'charset\s*=\s*["\']?([\w-]+)', re.I)


def dentro(base: pathlib.Path, alvo: pathlib.Path) -> bool:
    try:
        alvo.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


class Manipulador(http.server.BaseHTTPRequestHandler):
    server_version = "PDTeste/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silencioso
        pass

    def do_HEAD(self):
        self.tratar(corpo=False)

    def do_GET(self):
        self.tratar(corpo=True)

    def enviar(self, status, tipo, dados, corpo, extra=None):
        self.send_response(status)
        if tipo:
            self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            k_limpo = str(k).replace("\r", "").replace("\n", "").replace(":", "")
            v_limpo = str(v).replace("\r", "").replace("\n", "")
            self.send_header(k_limpo, v_limpo)
        self.end_headers()
        if corpo:
            self.wfile.write(dados)

    def redirecionar(self, destino, corpo):
        self.enviar(301, "text/plain; charset=utf-8", b"", corpo, {"Location": destino})

    def tratar(self, corpo):
        cfg = self.server.cfg
        partes = urllib.parse.urlsplit(self.path)
        caminho = urllib.parse.unquote(partes.path, encoding="utf-8", errors="replace")
        if cfg.legado:
            return self.tratar_legado(partes, caminho, corpo)
        prefixo = cfg.prefixo
        if caminho.startswith("/__testes__/") and cfg.testes:
            return self.servir_arquivo(cfg.testes, caminho[len("/__testes__/"):], partes, corpo, "/__testes__/")
        if caminho + "/" == prefixo:
            return self.redirecionar(prefixo + (("?" + partes.query) if partes.query else ""), corpo)
        if not caminho.startswith(prefixo):
            return self.nao_encontrado(corpo)
        return self.servir_arquivo(cfg.raiz, caminho[len(prefixo):], partes, corpo, prefixo)

    def servir_arquivo(self, base, rel, partes, corpo, prefixo):
        rel = posixpath.normpath("/" + rel).lstrip("/") if rel else ""
        alvo = base / rel if rel else base
        if not dentro(base, alvo):
            return self.nao_encontrado(corpo)
        if alvo.is_dir():
            if not partes.path.endswith("/"):
                destino = partes.path + "/" + (("?" + partes.query) if partes.query else "")
                return self.redirecionar(destino, corpo)
            alvo = alvo / "index.html"
        if not alvo.is_file():
            return self.nao_encontrado(corpo)
        tipo = TIPOS.get(alvo.suffix.lower(), "application/octet-stream")
        return self.enviar(200, tipo, alvo.read_bytes(), corpo)

    def nao_encontrado(self, corpo):
        p404 = self.server.cfg.raiz / "404.html"
        if not self.server.cfg.legado and p404.is_file():
            return self.enviar(404, TIPOS[".html"], p404.read_bytes(), corpo)
        return self.enviar(404, "text/plain; charset=utf-8", b"404", corpo)

    def tratar_legado(self, partes, caminho, corpo):
        if caminho != caminho.lower():
            destino = urllib.parse.quote(caminho.lower(), safe="/%") + (("?" + partes.query) if partes.query else "")
            return self.redirecionar(destino, corpo)
        rel = caminho[len(self.server.cfg.prefixo):] if caminho.startswith(self.server.cfg.prefixo) else None
        if rel is None:
            return self.nao_encontrado(corpo)
        base = self.server.cfg.raiz
        rel = posixpath.normpath("/" + rel).lstrip("/")
        alvo = base / rel
        if not rel or not dentro(base, alvo) or not alvo.is_file():
            return self.nao_encontrado(corpo)
        dados = alvo.read_bytes()
        if alvo.suffix.lower() in (".htm", ".html"):
            if "sem-charset=1" in (partes.query or ""):
                tipo = "text/html"
            else:
                m = META_CHARSET_RE.search(dados[:4096])
                utf8 = bool(m) and m.group(1).decode("ascii", "replace").lower() in ("utf-8", "utf8")
                tipo = "text/html; charset=" + ("utf-8" if utf8 else "windows-1252")
        else:
            tipo = TIPOS.get(alvo.suffix.lower(), "application/octet-stream")
        return self.enviar(200, tipo, dados, corpo)


class Servidor(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):  # conexão cortada pelo navegador: sem ruído
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Servidor estático de teste (imita o GitHub Pages).")
    ap.add_argument("--raiz", default=str(RAIZ / "docs"), help="pasta servida (padrão: docs/ do repo)")
    ap.add_argument("--prefixo", default="/planalto-direto/", help="subcaminho (padrão: /planalto-direto/)")
    ap.add_argument("--porta", type=int, default=0, help="porta (0 = livre)")
    ap.add_argument("--testes", default=str(RAIZ / "testes"), help="pasta montada em /__testes__/ ('' desliga)")
    ap.add_argument("--legado", action="store_true", help="serve páginas guardadas do Planalto (ver docstring)")
    a = ap.parse_args(argv)
    prefixo = a.prefixo if a.prefixo.endswith("/") else a.prefixo + "/"
    if not prefixo.startswith("/"):
        prefixo = "/" + prefixo
    raiz = pathlib.Path(a.raiz).resolve()
    if not raiz.is_dir():
        print(f"erro: --raiz não é pasta: {a.raiz}", file=sys.stderr)
        return 2
    srv = Servidor(("127.0.0.1", a.porta), Manipulador)
    srv.cfg = argparse.Namespace(raiz=raiz, prefixo=prefixo, legado=a.legado,
                                 testes=pathlib.Path(a.testes).resolve() if a.testes and not a.legado else None)
    print(srv.server_address[1], flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
