"""Orquestra as checagens do Planalto Direto e imprime PASS/FAIL/SKIP (SPEC §14.1).

Uso:
  python -P -B testes/rodar_tudo.py [--rapido] [--cache-html DIR] [--termos-proibidos ARQ]
                                    [--lista-privada ARQ ...] [--ancoras ARQ] [--navegador CAMINHO]
                                    [--instalar-semgrep] [--semgrep-registro] [--so ID[,ID...]]

Cada caminho privado também pode vir da variável de ambiente correspondente (PD_CACHE_HTML,
PD_TERMOS_PROIBIDOS, PD_LISTA_PRIVADA separada por ';', PD_ANCORAS, PD_NAVEGADOR).
Contrato das checagens: código 0 = PASS, 1 = FAIL, 77 = SKIP (razão na última linha, "SKIP: ..."),
2 = erro de uso; cada uma grava ``--json`` em testes/.saida/.
SKIP não é aprovação. Sai com 1 se houver algum FAIL.

--rapido = U0, U1, U2 e J1 (testes Python e Node, sem navegador e sem as páginas locais do Planalto).
"""
from __future__ import annotations

import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import argparse
import json
import os
import shutil
import subprocess
import tempfile

SAIDA = RAIZ / "testes" / ".saida"
PY = [sys.executable, "-P", "-B"]
MIN_NORMAS_REAIS = 21024
ORDEM = ("U0", "U1", "U2", "U3", "J1", "a", "b", "b2", "c", "d", "e", "f")
RAPIDO = ("U0", "U1", "U2", "J1")
PRECISA_SITE_REAL = ("J1", "a", "b", "c", "f")
ENTRADAS = ("build/montar_base.py", "build/gerar_site.py", "atualizador/atualizar.py")
TIMEOUT = 3600


class Contexto:
    def __init__(self, a):
        self.cache = a.cache_html or os.environ.get("PD_CACHE_HTML", "")
        self.termos = a.termos_proibidos or os.environ.get("PD_TERMOS_PROIBIDOS", "")
        self.listas = a.lista_privada or [x for x in os.environ.get("PD_LISTA_PRIVADA", "").split(";") if x]
        self.ancoras = a.ancoras or os.environ.get("PD_ANCORAS", "")
        self.navegador = a.navegador or os.environ.get("PD_NAVEGADOR", "")
        self.instalar_semgrep = a.instalar_semgrep
        self.semgrep_registro = a.semgrep_registro
        self.node = shutil.which("node")

    def nav_args(self) -> list[str]:
        return ["--navegador", self.navegador] if self.navegador else []


def rodar(cmd: list[str], json_arq: pathlib.Path | None = None, cwd=RAIZ, timeout=TIMEOUT) -> tuple[str, str]:
    """Roda um script de checagem e devolve (estado, detalhe) pelo contrato do §14.1."""
    if json_arq is not None and json_arq.exists():
        json_arq.unlink()
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "FAIL", f"tempo esgotado ({timeout} s)"
    except OSError as e:
        return "FAIL", f"não executou: {e}"
    out = r.stdout.decode("utf-8", "replace").strip().splitlines()
    err = r.stderr.decode("utf-8", "replace").strip().splitlines()
    ultima = out[-1].strip() if out else (err[-1].strip() if err else "")
    detalhe = ultima
    if json_arq is not None and json_arq.is_file():
        try:
            detalhe = json.loads(json_arq.read_text(encoding="utf-8")).get("detalhe") or ultima
        except ValueError:
            pass
    if r.returncode == 0:
        return "PASS", detalhe
    if r.returncode == 77:
        return "SKIP", (ultima[5:].strip() if ultima.startswith("SKIP:") else detalhe) or "sem razão informada"
    if r.returncode == 2:
        return "FAIL", "erro de uso: " + (err[-1] if err else detalhe)
    return "FAIL", detalhe or f"código {r.returncode}"


def site_real() -> tuple[bool, str]:
    man = RAIZ / "docs" / "dados" / "manifesto.json"
    if not man.is_file():
        return False, "docs/dados/manifesto.json ausente (rode build/gerar_site.py)"
    n = json.loads(man.read_text(encoding="utf-8")).get("normas", 0)
    if n < MIN_NORMAS_REAIS:
        return False, f"site gerado da fixture ({n} normas < {MIN_NORMAS_REAIS})"
    return True, ""


# ------------------------------------------------------------------ checagens
def ch_U0(ctx):
    scripts = list(ENTRADAS) + sorted(p.relative_to(RAIZ).as_posix() for p in (RAIZ / "testes").glob("*.py")
                                      if p.name != "__init__.py")
    falhas = []
    outra = tempfile.gettempdir()
    for s in scripts:
        if not (RAIZ / s).is_file():
            falhas.append(f"{s} ausente")
            continue
        try:
            r = subprocess.run(PY + [str(RAIZ / s), "--help"], cwd=outra, capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            falhas.append(f"{s}: {e}")
            continue
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip().splitlines()
            falhas.append(f"{s}: código {r.returncode} ({err[-1] if err else ''})")
    if falhas:
        return "FAIL", "; ".join(falhas)
    return "PASS", f"{len(scripts)} scripts respondem --help de outra pasta"


def ch_U1(ctx):
    return rodar(PY + ["-m", "unittest", "discover", "-s", "testes/py", "-t", "."])


def ch_U2(ctx):
    est, det = rodar(PY + ["build/gerar_site.py", "--verificar"])
    if est != "PASS":
        return est, "gerar_site --verificar: " + det
    insumos = all(os.environ.get(v) for v in ("PD_SNAPSHOT", "PD_ANCORAS", "PD_COMPILADOS")) and ctx.cache
    if not insumos:
        return "PASS", det + "; montar_base --verificar não rodou (sem os insumos do estágio A)"
    est2, det2 = rodar(PY + ["build/montar_base.py", "--verificar", "--cache-html", ctx.cache])
    if est2 != "PASS":
        return "FAIL", "montar_base --verificar: " + det2
    return "PASS", det + "; montar_base --verificar: idêntico"


def ch_U3(ctx):
    if not ctx.cache:
        return "SKIP", "páginas locais do Planalto não fornecidas (--cache-html)"
    estado = SAIDA / "estado-atualizador"
    return rodar(PY + ["atualizador/atualizar.py", "--estado", str(estado), "--offline-cache-raiz", ctx.cache,
                       "--modo", "todos", "--simular"])


def ch_J1(ctx):
    if not ctx.node:
        return "SKIP", "node não encontrado"
    # O Node 24 não aceita a pasta em --test; o padrão abaixo é expandido pelo próprio node.
    return rodar([ctx.node, "--test", "testes/js/*.test.js"])


def ch_a(ctx):
    if not ctx.node:
        return "SKIP", "node não encontrado"
    return rodar([ctx.node, "testes/navegador/rodar.mjs", "--casos", *ctx.nav_args(), "--json", str(SAIDA / "a.json")],
                 SAIDA / "a.json")


def ch_b(ctx):
    if not ctx.cache:
        return "SKIP", "páginas locais do Planalto não fornecidas (--cache-html)"
    if not ctx.node:
        return "SKIP", "node não encontrado"
    amostra = SAIDA / "amostra.json"
    est, det = rodar([ctx.node, "testes/links_amostra.mjs", "--cache-html", ctx.cache, "--saida", str(amostra)])
    if est != "PASS":
        return est, "links_amostra: " + det
    est, det = rodar(PY + ["testes/verifica_links.py", "--cache-html", ctx.cache, "--amostra", str(amostra),
                           "--json", str(SAIDA / "b-estatico.json")], SAIDA / "b-estatico.json")
    if est != "PASS":
        return est, "estático: " + det
    est2, det2 = rodar([ctx.node, "testes/navegador/rodar.mjs", "--ancoras-cache", "--cache-html", ctx.cache,
                        "--amostra", str(amostra), *ctx.nav_args(), "--json", str(SAIDA / "b-chrome.json")],
                       SAIDA / "b-chrome.json")
    if est2 != "PASS":
        return est2, "navegador: " + det2
    return "PASS", f"estático: {det}; navegador: {det2}"


def ch_b2(ctx):
    if not ctx.cache:
        return "SKIP", "páginas locais do Planalto não fornecidas (--cache-html)"
    return rodar(PY + ["testes/confere_avisos.py", "--cache-html", ctx.cache, "--json", str(SAIDA / "b2.json")],
                 SAIDA / "b2.json")


def ch_c(ctx):
    est, det = rodar(PY + ["testes/vazamento.py", "--marcas", "--json", str(SAIDA / "c-marcas.json")],
                     SAIDA / "c-marcas.json")
    if est != "PASS":
        return est, "marcas: " + det
    if not ctx.node:
        return "SKIP", "marcas: PASS; navegador: node não encontrado"
    est2, det2 = rodar([ctx.node, "testes/navegador/rodar.mjs", "--rodape", "--subcaminho", *ctx.nav_args(),
                        "--json", str(SAIDA / "c.json")], SAIDA / "c.json")
    if est2 != "PASS":
        return est2, "navegador: " + det2
    return "PASS", f"marcas: {det}; navegador: {det2}"


def ch_d(ctx):
    cmd = PY + ["testes/vazamento.py", "--historico", "--json", str(SAIDA / "d.json")]
    if ctx.termos:
        cmd += ["--termos-proibidos", ctx.termos]
    for x in ctx.listas:
        cmd += ["--lista-privada", x]
    if ctx.ancoras:
        cmd += ["--ancoras", ctx.ancoras]
    return rodar(cmd, SAIDA / "d.json")


def ch_e(ctx):
    cmd = PY + ["testes/semgrep.py", "--json", str(SAIDA / "e.json")]
    if ctx.instalar_semgrep:
        cmd.append("--instalar")
    if ctx.semgrep_registro:
        cmd.append("--config-registro")
    return rodar(cmd, SAIDA / "e.json")


def ch_f(ctx):
    if not ctx.node:
        return "SKIP", "node não encontrado"
    return rodar([ctx.node, "testes/navegador/rodar.mjs", "--celular", "--home", "--rede", *ctx.nav_args(),
                  "--json", str(SAIDA / "f.json")], SAIDA / "f.json")


CHECAGENS = {"U0": ("fumaça --help (python -P, outra pasta)", ch_U0),
             "U1": ("unitários Python", ch_U1),
             "U2": ("determinismo (estágios B e A)", ch_U2),
             "U3": ("atualizador offline", ch_U3),
             "J1": ("node:test sobre nucleo.js", ch_J1),
             "a": ("casos no navegador", ch_a),
             "b": ("links contra as páginas locais", ch_b),
             "b2": ("avisos conferidos", ch_b2),
             "c": ("rodapé, marcas, subcaminho", ch_c),
             "d": ("vazamento", ch_d),
             "e": ("Semgrep", ch_e),
             "f": ("celular, home rápida, rede", ch_f)}


def avisos_pendentes() -> list[str]:
    p = RAIZ / "fontes" / "avisos.json"
    if not p.is_file():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for a in d.get("avisos", []):
        if not a.get("conferido_em"):
            alvo = a.get("alvo", {})
            out.append(f"{a.get('id')} ({alvo.get('k')}{' / ' + alvo['disp'] if alvo.get('disp') else ''})")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Roda as checagens (U0–U3, J1, a–f) e imprime PASS/FAIL/SKIP.")
    ap.add_argument("--rapido", action="store_true", help="só U0, U1, U2 e J1")
    ap.add_argument("--cache-html")
    ap.add_argument("--termos-proibidos")
    ap.add_argument("--lista-privada", action="append")
    ap.add_argument("--ancoras")
    ap.add_argument("--navegador")
    ap.add_argument("--instalar-semgrep", action="store_true")
    ap.add_argument("--semgrep-registro", action="store_true",
                    help="(e) roda também os pacotes p/python, p/javascript e p/secrets do registro, sem métricas")
    ap.add_argument("--so", help="lista de ids separados por vírgula (ex.: U1,d)")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    ids = list(RAPIDO if a.rapido else ORDEM)
    if a.so:
        pedidos = [x.strip() for x in a.so.split(",") if x.strip()]
        desconhecidos = [x for x in pedidos if x not in CHECAGENS]
        if desconhecidos:
            print("erro: ids desconhecidos: " + ", ".join(desconhecidos), file=sys.stderr)
            return 2
        ids = [x for x in ORDEM if x in pedidos]
    SAIDA.mkdir(parents=True, exist_ok=True)
    ctx = Contexto(a)
    real, motivo_real = site_real()
    resultados = []
    for i in ids:
        nome, fn = CHECAGENS[i]
        print(f"... {i} {nome}", flush=True)
        if i in PRECISA_SITE_REAL and not real:
            resultados.append((i, "FAIL", motivo_real))
            continue
        try:
            est, det = fn(ctx)
        except Exception as e:  # uma checagem quebrada não derruba as outras
            est, det = "FAIL", f"exceção no orquestrador: {type(e).__name__}: {e}"
        resultados.append((i, est, det))
    print()
    print(f"{'checagem':<9}| {'estado':<5} | detalhe")
    print("-" * 80)
    for i, est, det in resultados:
        print(f"{i:<9}| {est:<5} | {det}")
    pend = avisos_pendentes()
    print()
    print(f"avisos pendentes de conferência: {len(pend)}")
    for p in pend:
        print(f"  - {p}")
    with open(SAIDA / "rodar_tudo.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"id": "rodar_tudo", "estado": "FAIL" if any(e == "FAIL" for _, e, _ in resultados) else "PASS",
                            "detalhe": f"{len(resultados)} checagens",
                            "itens": [{"id": i, "estado": e, "detalhe": d} for i, e, d in resultados]},
                           ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    return 1 if any(e == "FAIL" for _, e, _ in resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
