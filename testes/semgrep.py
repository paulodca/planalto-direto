"""(e) Semgrep (SPEC §14.6).

Uso:
  python -P -B testes/semgrep.py [--instalar] [--config-registro] [--config-auto] [--json ARQ]

Passos (cada um registra comando, código de saída e as últimas 20 linhas do stderr em
testes/.saida/semgrep.json):
  1. localizar: ``semgrep`` no PATH; senão ``python -P -m semgrep --version``; senão o executável
     no diretório de scripts do usuário. Localizado = ``--version`` responde com código 0.
  2. instalar (só com --instalar; única exceção de rede do projeto, e só ao PyPI):
     ``python -P -m pip install --user semgrep``; depois repete o passo 1.
  3. rodar: regras locais (``--config testes/semgrep.yml --error --metrics=off``, sem rede); com
     --config-registro, os pacotes do registro ``p/python``, ``p/javascript`` e ``p/secrets`` com
     ``--metrics=off`` (baixa as regras; o código não sai da máquina); e, só com --config-auto,
     ``--config auto`` (exige rede e métricas ligadas; não recomendado).
     PASS se rodar sem achado (PASS parcial se só as locais rodaram, com a razão no detalhe);
     FAIL se houver achado.
  4. SKIP (código 77) com a razão real colhida, se não for possível localizar, instalar ou rodar.
Códigos de saída: 0 PASS, 1 FAIL, 2 erro de uso, 77 SKIP.
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
import sysconfig

ID_CHECAGEM = "e"
ALVOS = ("pd", "build", "atualizador", "testes", "docs/assets", "docs/config.js", ".github", "modelos")
EXCLUIR = ("testes/.saida", "testes/fixtures", "node_modules", "__pycache__")
PACOTES_REGISTRO = ("p/python", "p/javascript", "p/secrets")


class Registro:
    def __init__(self):
        self.passos: list[dict] = []

    def rodar(self, cmd: list[str], env=None, timeout=900) -> subprocess.CompletedProcess | None:
        try:
            r = subprocess.run(cmd, cwd=RAIZ, capture_output=True, env=env, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as e:
            self.passos.append({"comando": " ".join(_mostrar(cmd)), "codigo": None, "stderr": [str(e)]})
            return None
        err = r.stderr.decode("utf-8", "replace").splitlines()[-20:]
        self.passos.append({"comando": " ".join(_mostrar(cmd)), "codigo": r.returncode, "stderr": err})
        return r


def _mostrar(cmd: list[str]) -> list[str]:
    """Comando sem caminhos absolutos da máquina (só o nome do executável)."""
    return [pathlib.Path(c).name if os.path.isabs(c) else c for c in cmd]


def _ultima_linha_util(passo: dict) -> str:
    for ln in reversed(passo.get("stderr") or []):
        ln = ln.strip()
        if ln:
            return ln[:300]
    return f"código {passo.get('codigo')}"


def _env(extra_path: str | None = None) -> dict:
    env = dict(os.environ)
    env["SEMGREP_ENABLE_VERSION_CHECK"] = "0"
    env["SEMGREP_SEND_METRICS"] = "off"
    if extra_path:
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
    return env


def localizar(reg: Registro) -> tuple[list[str] | None, dict, str]:
    """Devolve (comando base, ambiente, razão da falha)."""
    razoes = []
    exe = shutil.which("semgrep")
    if exe:
        r = reg.rodar([exe, "--version"], env=_env())
        if r is not None and r.returncode == 0:
            return [exe], _env(), ""
        razoes.append("semgrep no PATH falhou: " + _ultima_linha_util(reg.passos[-1]))
    r = reg.rodar([sys.executable, "-P", "-m", "semgrep", "--version"], env=_env())
    if r is not None and r.returncode == 0:
        return [sys.executable, "-P", "-m", "semgrep"], _env(), ""
    razoes.append("python -m semgrep falhou: " + _ultima_linha_util(reg.passos[-1]))
    scripts = sysconfig.get_path("scripts", f"{os.name}_user")
    for nome in ("semgrep.exe", "semgrep"):
        cand = pathlib.Path(scripts) / nome
        if cand.is_file():
            env = _env(scripts)
            r = reg.rodar([str(cand), "--version"], env=env)
            if r is not None and r.returncode == 0:
                return [str(cand)], env, ""
            razoes.append(f"{nome} do usuário falhou: " + _ultima_linha_util(reg.passos[-1]))
            break
    else:
        razoes.append("executável não encontrado no diretório de scripts do usuário")
    return None, _env(), "; ".join(razoes)


def instalar(reg: Registro) -> str:
    r = reg.rodar([sys.executable, "-P", "-m", "pip", "install", "--user", "semgrep"], timeout=1800)
    if r is None or r.returncode != 0:
        return "pip: " + _ultima_linha_util(reg.passos[-1])
    return ""


def _achados(saida_json: bytes) -> list[str]:
    try:
        d = json.loads(saida_json.decode("utf-8", "replace") or "{}")
    except ValueError:
        return []
    out = []
    for x in d.get("results", []):
        out.append(f"{x.get('path')}:{(x.get('start') or {}).get('line')}:{x.get('check_id')}")
    return out


def escanear(reg: Registro, base: list[str], env: dict, config: list[str]) -> tuple[str, list[str], str]:
    """('ok'|'achados'|'erro', achados, razão)."""
    alvos = [a for a in ALVOS if (RAIZ / a).exists()]
    cmd = base + ["scan", *config, "--error", "--json", "--quiet"]
    for e in EXCLUIR:
        cmd += ["--exclude", e]
    cmd += alvos
    r = reg.rodar(cmd, env=env)
    if r is None:
        return "erro", [], _ultima_linha_util(reg.passos[-1])
    achados = _achados(r.stdout)
    if r.returncode == 0:
        return "ok", [], ""
    if r.returncode == 1 and achados:
        return "achados", achados, ""
    return "erro", achados, _ultima_linha_util(reg.passos[-1])


def gravar(destinos, estado, detalhe, reg: Registro, achados):
    doc = {"id": ID_CHECAGEM, "estado": estado, "detalhe": detalhe, "itens": achados, "passos": reg.passos}
    for d in destinos:
        if not d:
            continue
        p = pathlib.Path(d)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Checagem (e): Semgrep com regras locais (e do registro, se pedido).")
    ap.add_argument("--instalar", action="store_true", help="tenta python -P -m pip install --user semgrep")
    ap.add_argument("--config-registro", action="store_true",
                    help="roda também os pacotes do registro " + ", ".join(PACOTES_REGISTRO)
                    + " com --metrics=off (baixa as regras; não envia código)")
    ap.add_argument("--config-auto", action="store_true",
                    help="roda também --config auto (exige rede até semgrep.dev e métricas ligadas)")
    ap.add_argument("--json", help="grava o resultado também neste arquivo")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    reg = Registro()
    destinos = [str(RAIZ / "testes" / ".saida" / "semgrep.json"), a.json]
    base, env, razao = localizar(reg)
    if base is None and a.instalar:
        r_inst = instalar(reg)
        base, env, razao2 = localizar(reg)
        razao = "; ".join(x for x in (razao, r_inst, razao2) if x)
    if base is None:
        detalhe = "semgrep indisponível: " + (razao or "motivo não colhido")
        if not a.instalar:
            detalhe += " (instalação não tentada; use --instalar)"
        gravar(destinos, "SKIP", detalhe, reg, [])
        for p in reg.passos:
            print(f"[{p['codigo']}] {p['comando']}")
        print("SKIP: " + detalhe)
        return 77
    estado_l, achados_l, razao_l = escanear(reg, base, env, ["--config", str(RAIZ / "testes" / "semgrep.yml"),
                                                                "--metrics=off"])
    if estado_l == "erro":
        detalhe = "semgrep: as regras locais não rodaram: " + razao_l
        gravar(destinos, "SKIP", detalhe, reg, achados_l)
        print("SKIP: " + detalhe)
        return 77
    achados = list(achados_l)
    notas = []
    if a.config_registro:
        cfg = []
        for pacote in PACOTES_REGISTRO:
            cfg += ["--config", pacote]
        estado_r, achados_r, razao_r = escanear(reg, base, env, cfg + ["--metrics=off"])
        achados += achados_r
        if estado_r == "erro":
            notas.append("pacotes do registro: não rodaram (" + razao_r + ")")
        else:
            notas.append("pacotes do registro (" + ", ".join(PACOTES_REGISTRO) + ") rodaram")
    if a.config_auto:
        estado_a, achados_a, razao_a = escanear(reg, base, _env(None) | {"SEMGREP_SEND_METRICS": "on"},
                                                ["--config", "auto"])
        achados += achados_a
        nota_auto = "" if estado_a != "erro" else "semgrep --config auto: não rodou (" + razao_a + ")"
    else:
        registro_ok = a.config_registro and notas and notas[-1].endswith("rodaram")
        nota_auto = "" if registro_ok else (
            "regras do registro não executadas (use --config-registro: p/python, p/javascript e p/secrets, "
            "sem métricas)")
    for x in achados:
        print(x)
    if achados:
        detalhe = f"{len(achados)} achado(s)"
        gravar(destinos, "FAIL", detalhe, reg, achados)
        print("FAIL: " + detalhe)
        return 1
    detalhe = "regras locais sem achado" + "".join("; " + n for n in notas)         + (f"; PASS parcial: {nota_auto}" if nota_auto else "")
    gravar(destinos, "PASS", detalhe, reg, [])
    print("PASS: " + detalhe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
