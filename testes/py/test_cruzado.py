"""Testes cruzados JS x Python (SPEC §14.7): ordem pública, codificação do fragmento e nome da norma.

Rodam o nucleo.js com `node -e` a partir do Python. Sem Node no PATH, os testes são pulados.
"""
import sys, pathlib
RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import json
import random
import shutil
import subprocess
import unittest
import urllib.parse

NUCLEO = RAIZ / "docs" / "assets" / "nucleo.js"
NODE = shutil.which("node")

try:
    from pd import ordem as pd_ordem
except Exception:  # noqa: BLE001 - pacote do P1 ainda ausente
    pd_ordem = None
try:
    from pd import normas as pd_normas
except Exception:  # noqa: BLE001
    pd_normas = None


def rodar_js(funcao: str, entradas: list) -> list:
    """Aplica PDNucleo.<funcao>(...args) a cada lista de argumentos; devolve os resultados."""
    script = (
        "const N=require(process.argv[1]);let d='';process.stdin.on('data',c=>d+=c);"
        "process.stdin.on('end',()=>{const e=JSON.parse(d);const f=process.argv[2];"
        "const out=e.map(a=>{if(f==='ordemPublica')return N.ordemPublica(a[0],new Set(a[1]));return N[f](...a);});"
        "process.stdout.write(JSON.stringify(out));});"
    )
    r = subprocess.run([NODE, "-e", script, str(NUCLEO), funcao], input=json.dumps(entradas).encode("utf-8"),
                       capture_output=True, timeout=120, check=True)
    return json.loads(r.stdout.decode("utf-8"))


def chaves_de_teste() -> list[str]:
    ks = set()
    arq = RAIZ / "testes" / "fixtures" / "base_min" / "normas.jsonl"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                ks.add(json.loads(linha)["k"])
    ks.update(["lei-5452-1968", "dl-5452-1943", "mp-100-1989", "mp-100-2002", "ec-132-2023", "lc-132-2009",
               "lei-5467a-1968", "lei-5467-1968", "cf-1988", "ecr-1-1994", "ld-1-1962", "dl-1-1937", "dl-1-1965"])
    return sorted(ks)


def ancoras_com_paragrafo() -> list[str]:
    nomes = set()
    for pasta in (RAIZ / "base" / "ancoras", RAIZ / "testes" / "fixtures" / "base_min" / "ancoras"):
        if not pasta.is_dir():
            continue
        for arq in pasta.glob("*.json"):
            dado = json.loads(arq.read_text(encoding="utf-8"))
            for parte in ("corpo", "adct"):
                for versoes in (dado.get(parte) or {}).values():
                    for nome in versoes.values():
                        if "§" in nome:
                            nomes.add(nome)
    return sorted(nomes)


@unittest.skipUnless(NODE, "node ausente no PATH")
class TestCruzado(unittest.TestCase):
    def test_codificar_fragmento(self):
        entradas = ["a§b!'()*~ç", "art477..", "art8§1", "cf-88-parte-1-titulo-2-capitulo-2-artigo-7",
                    "adctart76.2", " /?#&=+%", "ãõéº"] + ancoras_com_paragrafo()
        js = rodar_js("codificarFragmento", [[s] for s in entradas])
        for s, j in zip(entradas, js):
            self.assertEqual(j, urllib.parse.quote(s, safe=""), s)
        self.assertGreaterEqual(len(entradas), 7)

    @unittest.skipUnless(pd_ordem is not None, "pd.ordem ausente")
    def test_ordem_publica(self):
        ks = chaves_de_teste()
        rnd = random.Random(20261121)
        casos = []
        for _ in range(60):
            g = rnd.sample(ks, min(len(ks), rnd.randint(2, 12)))
            alvos = rnd.sample(g, rnd.randint(0, min(2, len(g))))
            casos.append([g, alvos])
        casos.append([ks, []])
        casos.append([["lei-5452-1968", "dl-5452-1943"], ["dl-5452-1943"]])
        js = rodar_js("ordemPublica", casos)
        for (g, alvos), j in zip(casos, js):
            self.assertEqual(j, pd_ordem.ordem_publica(g, set(alvos)), (g, alvos))

    @unittest.skipUnless(pd_normas is not None and hasattr(pd_normas, "nome_norma"), "pd.normas.nome_norma ausente")
    def test_nome_norma(self):
        casos = [["lei", 8036, "", "", 1990], ["dl", 5452, "", "", 1943], ["lei", 5467, "a", "", 1968],
                 ["mp", 2158, "", "35", 2001], ["lei", 605, "", "", 1949], ["cf", 1988, "", "", 1988],
                 ["lc", 150, "", "", 2015], ["ec", 132, "", "", 2023], ["ld", 13, "", "", 1992],
                 ["ecr", 6, "", "", 1994], ["lei", 10741, "", "", 2003], ["lei", 1000, "", "", 1950],
                 ["lei", 999, "", "", 1950], ["lei", 3890, "a", "", 1961], ["mp", 1045, "", "", 2021]]
        js = rodar_js("nomeNorma", casos)
        for c, j in zip(casos, js):
            self.assertEqual(j, pd_normas.nome_norma(*c), c)


if __name__ == "__main__":
    unittest.main()
