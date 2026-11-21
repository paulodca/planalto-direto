"""Atualizador (§13), sem rede: HTML sintético de fixture e relógio falso.

Toda abertura de URL é bloqueada durante estes testes: uma requisição acidental
falha alto em vez de sair para a rede.
"""
import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import types
import unittest
import urllib.error
from unittest import mock

from atualizador import indices, rede

# o módulo de requisições é alcançado pelo rede.py, o único que o importa (regra do Semgrep)
_req = rede.urllib.request
from atualizador import atualizar

try:
    from pd import cache_html, esquemas, jsonio, normas, ordem  # noqa: F401
    from atualizador import mesclar
    TEM_PD = True
except ModuleNotFoundError:  # pacote pd (P1) ainda não entregue
    TEM_PD = False

BASE = "https://www.planalto.gov.br/ccivil_03/"
FIXTURES = RAIZ / "testes" / "fixtures" / "indices"
F_RAIZ = FIXTURES / "www.planalto.gov.br" / "ccivil_03"
B_LEI = "_Ato2023-2026/2026/Lei/_leis2026.htm"
B_MP = "MPV/Quadro/_Quadro2023-2026.htm"
precisa_pd = unittest.skipUnless(TEM_PD, "pacote pd (P1) ausente")

HTML_OK = b"<html><body>" + b"x" * 200 + b"</body></html>"

_originais = {}


def _sem_rede(*a, **k):
    raise AssertionError("tentativa de acesso à rede durante os testes")


def setUpModule():
    _originais["urlopen"] = _req.urlopen
    _originais["open"] = _req.OpenerDirector.open
    _req.urlopen = _sem_rede
    _req.OpenerDirector.open = _sem_rede


def tearDownModule():
    _req.urlopen = _originais["urlopen"]
    _req.OpenerDirector.open = _originais["open"]


class Relogio:
    """Relógio falso: dormir só avança o tempo."""

    def __init__(self):
        self.t = 1000.0
        self.sonos = []
        self.t0 = time.time()

    def monotonic(self):
        return self.t

    def dormir(self, s):
        self.sonos.append(round(s, 6))
        self.t += s

    def agora(self):
        return self.t0 + (self.t - 1000.0)


class Abridor:
    """Respostas programadas: cada item é (status, corpo), uma exceção ou um callable."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        r = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(r, BaseException):
            raise r
        status, corpo = r
        return status, corpo, url


def _cliente(tmp, abridor, relogio=None, jitter=0.0, max_req=80, cache_horas=20.0, offline=None):
    r = relogio or Relogio()
    c = rede.Cliente(BASE, pathlib.Path(tmp), cache_horas, max_req, offline,
                     relogio=r.monotonic, dormir=r.dormir, agora=r.agora,
                     aleatorio=lambda a, b: jitter, abrir=abridor)
    return c, r


def _ler(rel):
    return (F_RAIZ / rel.lower()).read_bytes()


# ===================================================================== rede
class TestCorpoValido(unittest.TestCase):
    def test_tspd(self):
        self.assertEqual(rede.corpo_valido(b"<html>TSPD</html>", None), (False, "tspd"))

    def test_sem_fim_html(self):
        self.assertEqual(rede.corpo_valido(b"<html><body>truncado", None), (False, "sem </html>"))

    def test_fim_html_maiusculo_ok(self):
        self.assertEqual(rede.corpo_valido(b"<HTML>ok</HTML>", None), (True, ""))

    def test_menor_que_70(self):
        corpo = b"<html>" + b"a" * 600 + b"</html>"
        self.assertEqual(rede.corpo_valido(corpo, 1000), (False, "menor que 70%"))
        self.assertTrue(rede.corpo_valido(corpo, 800)[0])
        self.assertTrue(rede.corpo_valido(corpo, None)[0])


class TestConfigRede(unittest.TestCase):
    def test_user_agent_exato(self):
        self.assertEqual(rede.UA_BASE, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PlanaltoDireto/1.0")
        self.assertTrue(rede.UA == rede.UA_BASE or re.fullmatch(re.escape(rede.UA_BASE) + r" \(\+https://\S+/\)", rede.UA),
                        rede.UA)
        self.assertEqual(rede.CABECALHOS["User-Agent"], rede.UA)
        with mock.patch.dict(os.environ, {"PD_SITE_URL": "", "GITHUB_REPOSITORY": "dono/planalto-direto"}):
            self.assertEqual(rede._ua(), rede.UA_BASE + " (+https://dono.github.io/planalto-direto/)")
        with mock.patch.dict(os.environ, {"PD_SITE_URL": "", "GITHUB_REPOSITORY": ""}):
            self.assertEqual(rede._ua(), rede.UA_BASE)
        self.assertEqual((rede.INTERVALO_S, rede.BACKOFF_S, rede.FALHAS_MAX), (1.0, (5, 10, 20), 3))

    def test_cabecalhos_enviados(self):
        capturado = {}

        def falso_open(self, req, *a, **k):
            capturado["req"] = req
            raise urllib.error.URLError("sem rede no teste")

        _req.OpenerDirector.open = falso_open
        try:
            with self.assertRaises(urllib.error.URLError):
                rede.Cliente._abrir_urllib(BASE + "x.htm")
        finally:
            _req.OpenerDirector.open = _sem_rede
        req = capturado["req"]
        self.assertEqual(req.get_header("User-agent"), rede.UA)
        self.assertEqual(req.get_header("Accept-language"), "pt-BR,pt;q=0.9")

    def test_base_num_ponto_so(self):
        # a base do Planalto vem de docs/config.js; nenhum módulo do atualizador a escreve no código
        for nome in ("rede.py", "indices.py", "mesclar.py", "atualizar.py"):
            txt = (RAIZ / "atualizador" / nome).read_text(encoding="utf-8")
            self.assertNotRegex(txt, r"https?://(?:www\.)?planalto\.gov\.br", nome)


class TestCliente(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_backoff_e_parada(self):
        c, r = _cliente(self.tmp, Abridor(OSError("caiu")))
        with self.assertRaises(rede.Parada) as cm:
            c.obter("leis/a.htm", None)
        self.assertEqual(r.sonos, [5, 10])          # 3ª falha para, sem esperar 20 s
        self.assertEqual(c.requisicoes, 3)
        self.assertEqual(c.falhas, 3)
        self.assertIn("OSError", cm.exception.motivo)
        self.assertEqual(cm.exception.url, BASE + "leis/a.htm")

    def test_falhas_seguidas_atravessam_urls_e_zeram_no_sucesso(self):
        ab = Abridor((500, b""), (200, HTML_OK), (200, b"TSPD"), (200, b"TSPD"), (200, HTML_OK))
        c, r = _cliente(self.tmp, ab)
        self.assertIsNotNone(c.obter("a.htm", None))
        self.assertEqual(c.falhas_seguidas, 0)
        self.assertIsNotNone(c.obter("b.htm", None))   # 2 falhas e sucesso: não para
        self.assertEqual(c.falhas, 3)
        self.assertEqual([s for s in r.sonos if s >= 5], [5, 5, 10])

    def test_tres_falhas_em_urls_diferentes_param(self):
        ab = Abridor(urllib.error.URLError("x"), (200, HTML_OK), (503, b""), (503, b""), (503, b""))
        c, _ = _cliente(self.tmp, ab)
        c.obter("a.htm", None)
        with self.assertRaises(rede.Parada):
            c.obter("b.htm", None)

    def test_404_nao_e_falha(self):
        c, r = _cliente(self.tmp, Abridor((404, b"")))
        self.assertIsNone(c.obter("sumiu.htm", None))
        self.assertEqual((c.falhas, c.falhas_seguidas), (0, 0))
        self.assertEqual(r.sonos, [])

    def test_ritmo_um_por_segundo_com_jitter(self):
        c, r = _cliente(self.tmp, Abridor((200, HTML_OK)), jitter=0.3)
        c.obter("a.htm", None)
        c.obter("b.htm", None)
        c.obter("c.htm", None)
        self.assertEqual(r.sonos, [1.3, 1.3])

    def test_corpo_invalido_conta_como_falha(self):
        corpo = b"<html>" + b"a" * 100 + b"</html>"
        c, _ = _cliente(self.tmp, Abridor((200, corpo)))
        with self.assertRaises(rede.Parada) as cm:
            c.obter("a.htm", 1000)
        self.assertEqual(cm.exception.motivo, "menor que 70%")

    def test_cache_valido_dispensa_rede(self):
        c, r = _cliente(self.tmp, Abridor((200, HTML_OK)))
        c.obter("Leis/QUADRO/X.htm", None)
        arq = pathlib.Path(self.tmp, "cache", "www.planalto.gov.br", "ccivil_03", "leis", "quadro", "x.htm")
        self.assertEqual(arq.read_bytes(), HTML_OK)
        c2, _ = _cliente(self.tmp, Abridor(AssertionError("não devia ir à rede")), relogio=r)
        resp = c2.obter("Leis/QUADRO/X.htm", None)
        self.assertTrue(resp.do_cache)
        self.assertEqual(c2.requisicoes, 0)

    def test_cache_velho_vai_a_rede(self):
        c, r = _cliente(self.tmp, Abridor((200, HTML_OK)), cache_horas=1)
        c.obter("x.htm", None)
        r.t += 2 * 3600
        c2, _ = _cliente(self.tmp, Abridor((200, HTML_OK)), relogio=r, cache_horas=1)
        self.assertFalse(c2.obter("x.htm", None).do_cache)
        self.assertEqual(c2.requisicoes, 1)

    def test_bytes_anterior_cru_vem_do_proprio_cache(self):
        c, _ = _cliente(self.tmp, Abridor((200, HTML_OK)))
        self.assertIsNone(c.bytes_anterior_cru("Leis/QUADRO/X.htm"))     # sem leitura anterior
        c.obter("Leis/QUADRO/X.htm", None)
        self.assertEqual(c.bytes_anterior_cru("leis/quadro/x.htm"), len(HTML_OK))

    def test_corpo_invalido_nao_entra_no_cache(self):
        c, _ = _cliente(self.tmp, Abridor((200, b"TSPD")))
        with self.assertRaises(rede.Parada):
            c.obter("x.htm", None)
        self.assertFalse(pathlib.Path(self.tmp, "cache").exists())

    def test_teto_de_requisicoes(self):
        c, _ = _cliente(self.tmp, Abridor((200, HTML_OK)), max_req=1)
        c.obter("a.htm", None)
        with self.assertRaises(rede.Parada) as cm:
            c.obter("b.htm", None)
        self.assertIn("teto", cm.exception.motivo)

    def test_offline(self):
        c, r = _cliente(self.tmp, Abridor(AssertionError("rede")), offline=FIXTURES)
        resp = c.obter(B_LEI, None)
        self.assertEqual(resp.raw, _ler(B_LEI))
        self.assertIsNone(c.obter("nao/existe.htm", None))
        with self.assertRaises(rede.Parada):
            c.obter("leis/QUADRO/1990.htm", None)    # fixture com TSPD
        self.assertEqual((c.requisicoes, r.sonos), (0, []))
        self.assertFalse(pathlib.Path(self.tmp, "cache").exists())

    def test_log_sem_campos_extras(self):
        c, _ = _cliente(self.tmp, Abridor((200, HTML_OK)))
        c.obter("a.htm", None)
        linhas = pathlib.Path(self.tmp, "log.jsonl").read_text(encoding="utf-8").splitlines()
        ev = json.loads(linhas[-1])
        self.assertEqual(ev["url_final"], BASE + "a.htm")
        self.assertEqual(ev["resultado"], "ok")


# =================================================================== parser
class TestExtratorTabela(unittest.TestCase):
    def test_arvore_minima(self):
        h = ("<script>var s='<table><tr><td>falso</td></tr></table>';</script>"
             "<table><tr><td>A<br>B<td>C<font>D</font>E"
             "<tr><td><a href='x.htm'>link 1</a> fora<td>2ª"
             "<table><tr><td>interna</table> depois</table>"
             "<p>fora de tabela</p>")
        linhas = indices.linhas_do_indice(h)
        textos = [[c["texto"] for c in ln] for ln in linhas]
        self.assertEqual(textos, [["A B", "CDE"], ["link 1 fora", "2ª depois"], ["interna"]])
        self.assertEqual(linhas[1][0]["links"], [("x.htm", "link 1")])

    def test_link_nao_fechado(self):
        linhas = indices.linhas_do_indice("<table><tr><td><a href='a.htm'>um<td>dois</table>")
        self.assertEqual(linhas[0][0]["links"], [("a.htm", "um")])
        self.assertEqual(linhas[0][1]["texto"], "dois")

    def test_entidades(self):
        linhas = indices.linhas_do_indice("<table><tr><td>a&#150;b&nbsp;c &amp; d</td></tr></table>")
        self.assertEqual(linhas[0][0]["texto"], "a–b c & d")

    def test_relativo_da_base(self):
        self.assertEqual(indices.relativo_da_base("http://WWW.planalto.gov.br/CCIVIL_03/Leis/L1.htm", BASE), "Leis/L1.htm")
        self.assertIsNone(indices.relativo_da_base("https://www.exemplo.org/ccivil_03/L1.htm", BASE))

    def test_numero_do_arquivo(self):
        self.assertEqual(indices.numero_do_arquivo("_Ato/Mpv/mpv692.htm", True), (692, "", ""))
        self.assertEqual(indices.numero_do_arquivo("MPV/2158-35.htm", True), (2158, "", "35"))
        self.assertEqual(indices.numero_do_arquivo("MPV/Antigas/1456.htm", True), (1456, "", ""))
        self.assertEqual(indices.numero_do_arquivo("leis/L10.741.htm", False), (10741, "", ""))
        self.assertIsNone(indices.numero_do_arquivo("leis/1456.htm", False))

    def test_numero_do_rotulo(self):
        self.assertEqual(indices.numero_do_rotulo("Lei nº 3.890-A, de 25.4.61"), (3890, "a", ""))
        self.assertEqual(indices.numero_do_rotulo("Medida Provisória nº 2.158-35, de 24.8.2001"), (2158, "", "35"))
        self.assertEqual(indices.numero_do_rotulo("8.036, de 11.5.90"), (8036, "", ""))

    def test_novos_buckets(self):
        h = indices.decodificar(_ler("leis/_lei-ordinaria.htm")) if TEM_PD else _ler("leis/_lei-ordinaria.htm").decode("cp1252")
        novos = indices.novos_buckets(h, "leis/_lei-ordinaria.htm", {B_LEI}, BASE)
        self.assertEqual(novos, ["_Ato2027-2030/2027/Lei/_leis2027.htm", "MPV/Quadro/_Quadro2027-2030.htm"])


@precisa_pd
class TestRegistros(unittest.TestCase):
    def _regs(self, caminho, tipo):
        return indices.registros_do_indice(indices.decodificar(_ler(caminho)), caminho, tipo, BASE)

    def test_bucket_de_lei(self):
        regs = self._regs(B_LEI, "lei")
        self.assertEqual([r["url"] for r in regs], [
            "_Ato2023-2026/2026/Lei/L99001.htm", "_Ato2023-2026/2026/Lei/L99002.htm",
            "_Ato2023-2026/2026/Lei/L99003.htm", "_Ato2023-2026/2026/Lei/L99004-A.htm",
            "_Ato2023-2026/2026/Lei/L99005.htm"])
        r1 = regs[0]
        self.assertEqual(r1["rotulo"], "Lei nº 99.001, de 5.1.2026")
        self.assertEqual(r1["data_txt"], "de 5.1.2026")
        self.assertEqual(r1["ementa"], "Cria o cadastro sintético de testes – parte A. Mensagem de veto")
        self.assertEqual((r1["numero"], r1["sufixo"], r1["indice"], r1["tipo"]), (99001, "", B_LEI, "lei"))
        self.assertEqual(regs[1]["rotulo"], "Lei nº 99.002, de 10.2.2026")
        self.assertEqual(regs[2]["ementa"], "Institui o programa sintético B.")   # riscado é ignorado
        self.assertEqual((regs[3]["numero"], regs[3]["sufixo"], regs[3]["ementa"]),
                         (99004, "a", "Norma sintética com letra. Fim."))

    def test_bucket_de_mp_com_rotulo_truncado(self):
        regs = self._regs(B_MP, "medida provisoria")
        self.assertEqual([(r["numero"], r["sufixo"]) for r in regs], [(1901, ""), (1902, ""), (1903, "-2")])
        self.assertIn("arquivo diz 1902", regs[1]["divergencia"])
        self.assertEqual(regs[0]["ementa"], "Abre crédito sintético para testes. Convertida na Lei nº 99.001, de 2026.")
        self.assertEqual(regs[0]["rotulo"], "Medida Provisória nº 1.901, de 7.1.2026")   # UTF-8 declarado

    def test_rotulo_partido_e_nome_do_arquivo(self):
        h = ("<html><table>"
             "<tr><td><a href='L0091.htm'>92</a><a href='L0092.htm'>, de 6.6.2026</a></td><td>Ementa X.</td></tr>"
             "<tr><td><a href='L0091.htm'>91, de 5.6.2026</a></td><td>Ementa Y.</td></tr>"
             "<tr><td><a href='../Mpv/mpv1801.htm'>Medida Provisória nº 1.801</a>"
             "<strike><a href='../Mpv/mpv1802.htm'>Rejeitada pela Medida Provisória nº 1.802, de 2026</a></strike>"
             "</td><td>Ementa Z.</td></tr></table></html>")
        regs = indices.registros_do_indice(h, "_Ato2023-2026/2026/Lei/_leis2026.htm", "lei", BASE)
        self.assertEqual([(r["url"].rsplit("/", 1)[1], r["numero"], r["ementa"]) for r in regs], [
            ("L0091.htm", 91, "Ementa X."), ("L0092.htm", 92, "Ementa X."), ("L0091.htm", 91, "Ementa Y."),
            ("mpv1801.htm", 1801, "Ementa Z.")])
        self.assertIn("arquivo diz 91", regs[0]["divergencia"])
        self.assertEqual(regs[1]["rotulo"], ", de 6.6.2026")
        regs = indices.registros_do_indice(h, B_MP, "medida provisoria", BASE)
        self.assertEqual([r["numero"] for r in regs if "Mpv" in r["url"]], [1801])

    def test_ementa_limpa(self):
        regs = self._regs(B_MP, "medida provisoria")
        self.assertEqual(normas.limpar_ementa(regs[0]["ementa"], "medida provisoria"),
                         "Abre crédito sintético para testes.")


# ===================================================================== lock
class TestLock(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ocupado(self):
        arq = atualizar.adquirir_lock(self.tmp, False)
        self.assertRegex(arq.read_text(encoding="utf-8"), r"^\d+ \d{4}-\d{2}-\d{2}T")
        with self.assertRaises(atualizar.LockOcupado) as cm:
            atualizar.adquirir_lock(self.tmp, True)
        self.assertNotIn("velho", str(cm.exception))

    def test_velho(self):
        arq = atualizar.adquirir_lock(self.tmp, False)
        velho = time.time() - 4 * 3600
        os.utime(arq, (velho, velho))
        with self.assertRaises(atualizar.LockOcupado) as cm:
            atualizar.adquirir_lock(self.tmp, False)
        self.assertIn("lock velho; use --remover-lock-velho", str(cm.exception))
        self.assertTrue(atualizar.adquirir_lock(self.tmp, True).exists())

    def test_main_sai_com_3_e_nao_remove_lock_alheio(self):
        arq = atualizar.adquirir_lock(self.tmp, False)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(atualizar.main(["--estado", str(self.tmp)]), 3)
        self.assertTrue(arq.exists())


# =================================================================== mescla
def _norma(k, caminho, indice, ementa="Ementa sintética.", rotulo=None, **extra):
    t, n, l, a = ordem.partes_chave(k)
    d = {"ano": a, "caminho": caminho, "caminho_compilado": "", "caminho_indice": caminho,
         "data": "", "desde": "2026-11-21", "ementa": ementa, "indice": indice, "k": k, "letra": l,
         "numero": n, "reed": "", "rotulo": rotulo or f"{n}, de 2026", "tipo": normas.TSIG_TIPO[t], "tsig": t}
    d.update(extra)
    return d


def _base_fixture():
    return [
        _norma("lei-99002-2026", "_Ato2023-2026/2026/Lei/L99002.htm", B_LEI, ementa="Texto antigo.",
               rotulo="Lei nº 99.002, de 10.2.2026"),
        _norma("lei-99003-2026", "leis/outra/L99003x.htm", "leis/outra/_quadro.htm"),
        _norma("lei-99009-2026", "_Ato2023-2026/2026/Lei/L99009.htm", B_LEI),
    ]


@precisa_pd
class TestMesclar(unittest.TestCase):
    def _brutos(self):
        out = []
        for c, t in ((B_LEI, "lei"), (B_MP, "medida provisoria")):
            out += indices.registros_do_indice(indices.decodificar(_ler(c)), c, t, BASE)
        return out

    def test_mescla(self):
        base = _base_fixture()
        saida, diff = mesclar.mesclar(base, self._brutos(), "2026-12-01", 2026, base_url=BASE,
                                      indices_lidos={B_LEI, B_MP})
        self.assertEqual(diff["novas"], ["lei-99001-2026", "lei-99004a-2026", "lei-99005-2026",
                                         "mp-1901-2026", "mp-1902-2026", "mp-1903-2026"])
        self.assertEqual(diff["sumidas"], ["lei-99009-2026"])
        self.assertEqual([c["k"] for c in diff["conflitos"]], ["lei-99003-2026"])
        self.assertEqual(diff["alteradas"], [{"k": "lei-99002-2026", "campo": "ementa", "antes": "Texto antigo.",
                                              "depois": "Altera a Lei nº 99.001, de 5 de janeiro de 2026, para fins de teste."}])
        self.assertEqual(len(diff["divergencias"]), 1)
        por_k = {n["k"]: n for n in saida}
        n1 = por_k["lei-99001-2026"]
        self.assertEqual(n1["ementa"], "Cria o cadastro sintético de testes – parte A.")
        self.assertEqual((n1["caminho"], n1["caminho_indice"], n1["caminho_compilado"], n1["desde"], n1["data"]),
                         ("_Ato2023-2026/2026/Lei/L99001.htm",) * 2 + ("", "2026-12-01", "2026-01-05"))
        self.assertEqual(por_k["mp-1903-2026"]["reed"], "2")
        self.assertEqual(por_k["mp-1901-2026"]["ementa"], "Abre crédito sintético para testes.")
        self.assertEqual(por_k["lei-99004a-2026"]["letra"], "a")
        self.assertEqual(por_k["lei-99009-2026"], base[2])            # nunca apaga
        self.assertEqual(esquemas.validar_normas(saida), [])
        self.assertEqual(mesclar.verificar(saida, diff), [])
        self.assertEqual(base[0]["ementa"], "Texto antigo.")          # entrada não é alterada

    def test_existente_nao_recalcula(self):
        b = _norma("lei-99002-2025", "_Ato2023-2026/2026/Lei/L99002.htm", B_LEI, rotulo="Lei nº 99.002, de 10.2.2026",
                   ementa="Altera a Lei nº 99.001, de 5 de janeiro de 2026, para fins de teste.", desde="2020-01-01")
        b["caminho"] = "leis/l99002compilado.htm"
        b["caminho_indice"] = "_ATO2023-2026/2026/LEI/L99002.HTM"
        saida, diff = mesclar.mesclar([b], self._brutos()[:2], "2026-12-01", 2026, base_url=BASE)
        n = [x for x in saida if x["numero"] == 99002][0]
        self.assertEqual((n["k"], n["ano"], n["caminho"], n["desde"]),
                         ("lei-99002-2025", 2025, "leis/l99002compilado.htm", "2020-01-01"))
        self.assertEqual(diff["alteradas"], [])

    def test_trava_de_500(self):
        brutos = [{"url": f"_Ato2023-2026/2026/Lei/L{90000 + i}.htm", "rotulo": f"Lei nº {90000 + i}, de 1.2.2026",
                   "data_txt": "de 1.2.2026", "ementa": "Sintética.", "tipo": "lei", "indice": B_LEI,
                   "numero": 90000 + i, "sufixo": "", "divergencia": ""} for i in range(501)]
        saida, diff = mesclar.mesclar([], brutos, "2026-12-01", 2026, base_url=BASE)
        self.assertEqual(len(diff["novas"]), 501)
        self.assertTrue(any("--aceitar-muitas" in e for e in mesclar.verificar(saida, diff)))
        self.assertEqual(mesclar.verificar(saida, diff, aceitar_muitas=True), [])

    def test_gate_de_ementa(self):
        n = _norma("mp-1901-2026", "_Ato2023-2026/2026/Mpv/mpv1901.htm", B_MP, ementa="Algo. Sem eficácia")
        diff = {"novas": ["mp-1901-2026"], "alteradas": [], "sumidas": [], "conflitos": []}
        self.assertTrue(mesclar.verificar([n], diff))

    def test_conferir(self):
        brutos = self._brutos()
        saida, _ = mesclar.mesclar([], brutos, "2026-11-21", 2026, base_url=BASE)
        conf = mesclar.conferir(saida, brutos, BASE, 2026)
        self.assertEqual((conf["igualdade"], conf["ementa_diferente"]), (1.0, 0))
        saida[0] = dict(saida[0], ano=1999)
        conf = mesclar.conferir(saida, brutos, BASE, 2026)
        self.assertLess(conf["igualdade"], 1.0)
        self.assertEqual(len(conf["so_na_base"]), 1)


# ============================================================ ponta a ponta
@precisa_pd
class TestAtualizarOffline(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.base = self.tmp / "base"
        self.estado = self.tmp / "estado"
        self.base.mkdir()
        jsonio.escrever_jsonl(self.base / "normas.jsonl", sorted(_base_fixture(), key=lambda n: ordem.ordem_chave(n["k"])))
        jsonio.escrever_json(self.base / "indices.json", {"indices": {
            B_LEI: {"bytes": 100, "quando": "2026-11-20", "sha256": "0" * 64}}, "versao": 1})
        self.lb = self.tmp / "lista_branca.json"
        shutil.copy(RAIZ / "atualizador" / "lista_branca.json", self.lb)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rodar(self, *extra):
        argv = ["--estado", str(self.estado), "--base", str(self.base), "--offline-cache-raiz", str(FIXTURES),
                "--hoje", "2026-12-01", "--sem-regerar", "--lista-branca", str(self.lb), *extra]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cod = atualizar.main(argv)
        self.saida = out.getvalue()
        return cod

    def _relatorio(self):
        return json.loads((self.estado / "relatorios" / "atualizacao-2026-12-01.json").read_text(encoding="utf-8"))

    def test_grava(self):
        antes_lb = self.lb.read_bytes()
        self.assertEqual(self._rodar("--indice", B_LEI, B_MP), 0, self.saida)
        normas_lidas = jsonio.ler_jsonl(self.base / "normas.jsonl")
        self.assertEqual(esquemas.validar_normas(normas_lidas), [])
        ks = [n["k"] for n in normas_lidas]
        self.assertIn("mp-1902-2026", ks)
        self.assertEqual(len(ks), 3 + 6)
        idx = jsonio.ler_json(self.base / "indices.json")
        self.assertEqual(esquemas.validar_indices(idx), [])
        self.assertEqual(idx["indices"][B_LEI]["bytes"], len(_ler(B_LEI)))
        self.assertEqual(idx["indices"][B_LEI]["quando"], "2026-12-01")
        self.assertIn(B_MP, idx["indices"])
        rel = self._relatorio()
        self.assertEqual(len(rel["diff"]["novas"]), 6)
        self.assertEqual(rel["novas_detalhe"][0]["link"], BASE + "_Ato2023-2026/2026/Lei/L99001.htm")
        md = (self.estado / "relatorios" / "atualizacao-2026-12-01.md").read_text(encoding="utf-8")
        self.assertIn("Lei nº 99.001/2026", md)
        self.assertFalse((self.estado / "coleta.lock").exists())
        self.assertEqual(self.lb.read_bytes(), antes_lb)
        for arq in (self.base / "normas.jsonl", self.base / "indices.json"):
            dados = arq.read_bytes()
            self.assertNotIn(b"\r", dados)
            self.assertFalse(dados.startswith(b"\xef\xbb\xbf"))
        # segunda execução: nada novo, mesma base
        antes = (self.base / "normas.jsonl").read_bytes()
        self.assertEqual(self._rodar("--indice", B_LEI, B_MP), 0)
        self.assertEqual((self.base / "normas.jsonl").read_bytes(), antes)
        self.assertEqual(self._relatorio()["diff"]["novas"], [])

    def test_simular_nao_grava(self):
        antes = (self.base / "normas.jsonl").read_bytes(), (self.base / "indices.json").read_bytes()
        self.assertEqual(self._rodar("--indice", B_LEI, B_MP, "--simular"), 0)
        self.assertEqual(((self.base / "normas.jsonl").read_bytes(), (self.base / "indices.json").read_bytes()), antes)
        self.assertIn("conferencia", self._relatorio())

    def test_parada_nao_grava(self):
        antes = (self.base / "normas.jsonl").read_bytes()
        self.assertEqual(self._rodar("--indice", B_LEI, "leis/QUADRO/1990.htm"), 2)
        self.assertEqual((self.base / "normas.jsonl").read_bytes(), antes)
        rel = self._relatorio()
        self.assertEqual(rel["parada"]["motivo"], "tspd")
        self.assertIn("parada", self.saida)

    def test_70_por_cento_sem_leitura_anterior_so_avisa(self):
        # base/indices.json com "bytes" enorme (HTML reformatado) não dispara a regra dos 70%
        jsonio.escrever_json(self.base / "indices.json", {"indices": {
            B_LEI: {"bytes": 10 ** 9, "quando": "2026-11-20", "sha256": "0" * 64}}, "versao": 1})
        self.assertEqual(self._rodar("--indice", B_LEI, "--simular"), 0, self.saida)
        rel = self._relatorio()
        self.assertEqual(rel["sem_leitura_anterior"], [B_LEI])
        self.assertTrue(any("70%" in a for a in rel["avisos"]), rel["avisos"])
        self.assertIn("aviso:", self.saida)

    def test_70_por_cento_contra_a_leitura_crua_anterior(self):
        cache = rede.caminho_local(self.estado / "cache", B_LEI, BASE)
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"<html>" + b"x" * (2 * len(_ler(B_LEI))) + b"</html>")
        antes = (self.base / "normas.jsonl").read_bytes()
        self.assertEqual(self._rodar("--indice", B_LEI), 2, self.saida)
        rel = self._relatorio()
        self.assertEqual(rel["parada"]["motivo"], "menor que 70%")
        self.assertEqual(rel["sem_leitura_anterior"], [])
        self.assertEqual((self.base / "normas.jsonl").read_bytes(), antes)
        # leitura anterior do mesmo tamanho: passa
        cache.write_bytes(_ler(B_LEI))
        self.assertEqual(self._rodar("--indice", B_LEI, "--simular"), 0, self.saida)

    def test_indice_fora_da_lista_branca(self):
        self.assertEqual(self._rodar("--indice", "leis/inventado.htm"), 2)

    def test_novos_buckets(self):
        nav = "leis/_lei-ordinaria.htm"
        self.assertEqual(self._rodar("--indice", nav), 0)
        rel = self._relatorio()
        self.assertEqual(rel["novos_indices"], ["_Ato2027-2030/2027/Lei/_leis2027.htm", "MPV/Quadro/_Quadro2027-2030.htm"])
        self.assertEqual(rel["diff"]["novas"], [])
        self.assertEqual(self._rodar("--indice", nav, "--aceitar-novos-indices"), 0)
        rel = self._relatorio()
        self.assertEqual(rel["diff"]["novas"], ["lei-99101-2027"])
        self.assertEqual(rel["indices_404"], ["MPV/Quadro/_Quadro2027-2030.htm"])
        lb = json.loads(self.lb.read_text(encoding="utf-8"))
        self.assertEqual(len(lb["indices"]), 67)
        self.assertEqual(lb["indices"][-2], {"caminho": "_Ato2027-2030/2027/Lei/_leis2027.htm",
                                             "papel": "bucket", "tipo": "lei"})

    def test_gate_de_dados_sai_com_4(self):
        normas_lidas = jsonio.ler_jsonl(self.base / "normas.jsonl")
        normas_lidas.append(_norma("lei-99001-2026", "leis/outro/L1.htm", "leis/outro/_quadro.htm"))
        normas_lidas.append(dict(normas_lidas[-1], caminho_indice="leis/outro/L2.htm"))
        jsonio.escrever_jsonl(self.base / "normas.jsonl", normas_lidas)
        antes = (self.base / "normas.jsonl").read_bytes()
        self.assertEqual(self._rodar("--indice", B_LEI), 4)
        self.assertEqual((self.base / "normas.jsonl").read_bytes(), antes)

    def test_regera_site_com_a_mesma_base(self):
        chamadas = []
        falso = types.ModuleType("build.gerar_site")
        falso.main = lambda argv=None: chamadas.append(argv) or 0
        import build
        guardado = sys.modules.get("build.gerar_site"), getattr(build, "gerar_site", None)
        sys.modules["build.gerar_site"] = falso
        build.gerar_site = falso
        try:
            argv = ["--estado", str(self.estado), "--base", str(self.base), "--offline-cache-raiz", str(FIXTURES),
                    "--hoje", "2026-12-01", "--lista-branca", str(self.lb), "--indice", B_LEI]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(atualizar.main(argv), 0)
        finally:
            if guardado[0] is None:
                sys.modules.pop("build.gerar_site", None)
            else:
                sys.modules["build.gerar_site"] = guardado[0]
            if guardado[1] is None:
                if hasattr(build, "gerar_site"):
                    del build.gerar_site
            else:
                build.gerar_site = guardado[1]
        self.assertEqual(chamadas, [["--base", str(self.base.resolve())]])


@precisa_pd
class TestSelecao(unittest.TestCase):
    def setUp(self):
        self.lb = json.loads((RAIZ / "atualizador" / "lista_branca.json").read_text(encoding="utf-8"))["indices"]

    def test_ano_corrente(self):
        sel, _ = atualizar.selecionar(self.lb, "ano-corrente", 2026, None, BASE)
        self.assertEqual(sorted(e["caminho"] for e in sel), sorted([
            "Constituicao/Emendas/Emc/quadro_emc.htm", "LEIS/LCP/Quadro_Lcp.htm",
            "MPV/Quadro/_Quadro2023-2026.htm", "_Ato2023-2026/2026/Lei/_leis2026.htm"]))

    def test_ano_sem_bucket_le_navegacao(self):
        sel, _ = atualizar.selecionar(self.lb, "ano-corrente", 2027, None, BASE)
        cams = [e["caminho"] for e in sel]
        self.assertEqual(cams[:2], ["MPV/Principal.htm", "leis/_lei-ordinaria.htm"])
        self.assertEqual(sorted(cams[2:]), ["Constituicao/Emendas/Emc/quadro_emc.htm", "LEIS/LCP/Quadro_Lcp.htm"])

    def test_todos(self):
        sel, _ = atualizar.selecionar(self.lb, "todos", 2026, None, BASE)
        self.assertEqual(len(sel), 65)


# ======================================================== arquivos estáticos
class TestListaBranca(unittest.TestCase):
    def test_formato(self):
        lb = json.loads((RAIZ / "atualizador" / "lista_branca.json").read_text(encoding="utf-8"))
        self.assertEqual(lb["versao"], 1)
        ind = lb["indices"]
        self.assertEqual(len(ind), 65)
        self.assertEqual(len({e["caminho"].lower() for e in ind}), 65)
        self.assertEqual(sum(e["papel"] == "bucket" for e in ind), 59)
        tipos = {"lei", "lei complementar", "decreto-lei", "medida provisoria", "emenda constitucional",
                 "lei delegada", "emenda constitucional de revisao"}
        for e in ind:
            self.assertEqual(set(e), {"caminho", "papel", "tipo"})
            if e["papel"] == "bucket":
                self.assertIn(e["tipo"], tipos)
            else:
                self.assertEqual((e["papel"], e["tipo"]), ("navegacao", None))
        if TEM_PD:
            self.assertTrue(tipos <= set(normas.TIPOS))


def _blocos_run(txt: str) -> list[str]:
    """Texto de cada ``run:`` (a linha e a continuação indentada)."""
    linhas = txt.splitlines()
    blocos = []
    for i, ln in enumerate(linhas):
        m = re.match(r"^(\s*)(?:- )?run:(.*)$", ln)
        if not m:
            continue
        bloco = [m.group(2)]
        for prox in linhas[i + 1:]:
            if prox.strip() and len(prox) - len(prox.lstrip()) <= len(m.group(1)):
                break
            bloco.append(prox)
        blocos.append("\n".join(bloco))
    return blocos


def _permissoes_do_topo(txt: str) -> dict:
    m = re.search(r"(?m)^permissions:\n((?:[ ]+\S.*\n)+)", txt)
    if not m:
        return {}
    return dict(re.match(r"^\s+([\w-]+):\s*(\S+)", ln).groups() for ln in m.group(1).splitlines())


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.txt = (RAIZ / ".github" / "workflows" / "atualizar.yml").read_text(encoding="utf-8")

    def test_so_manual(self):
        self.assertIn("workflow_dispatch:", self.txt)
        self.assertNotRegex(self.txt, r"(?m)^\s*(schedule|cron|push|pull_request)\s*:")

    def test_sem_interpolacao_em_run(self):
        blocos = _blocos_run(self.txt)
        for b in blocos:
            self.assertNotIn("${{", b)
        self.assertGreaterEqual(len(blocos), 3)

    def test_nao_versiona_o_site_gerado(self):
        (publicar,) = [b for b in _blocos_run(self.txt) if "git add" in b]
        add = re.search(r"git add ([^\n]+)", publicar).group(1).split()
        self.assertIn("base", add)
        for proibido in ("docs", "-A", "-f", "--force", "."):
            self.assertNotIn(proibido, add)

    def test_chama_o_pages_depois_do_push(self):
        # push com o GITHUB_TOKEN padrão não dispara o "push" de outro workflow: a chamada é explícita
        m = re.search(r"(?ms)^  pages:\n(.*?)(?=^  \S|\Z)", self.txt)
        self.assertIsNotNone(m, "job 'pages' ausente")
        job = m.group(1)
        self.assertIn("needs: atualizar", job)
        self.assertIn("uses: ./.github/workflows/pages.yml", job)
        self.assertIn("ref: ${{ needs.atualizar.outputs.commit }}", job)
        for p in ("contents: read", "pages: write", "id-token: write"):
            self.assertIn(p, job)

    def test_identidade_do_bot(self):
        # identidade neutra, sem e-mail nem login (e sem o git adivinhar usuario@maquina)
        self.assertIn('git config user.name "Planalto Direto"', self.txt)
        self.assertIn('git config user.email ""', self.txt)
        self.assertIn("git config user.useConfigOnly true", self.txt)
        self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", self.txt))


class TestWorkflowPages(unittest.TestCase):
    def setUp(self):
        self.txt = (RAIZ / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")

    def test_sem_agendamento(self):
        self.assertNotRegex(self.txt, r"(?m)^\s*(schedule|cron)\s*:")

    def test_gatilhos(self):
        for g in ("push:", "workflow_dispatch:", "workflow_call:"):
            self.assertRegex(self.txt, r"(?m)^  " + re.escape(g))
        self.assertNotRegex(self.txt, r"(?m)^\s*pull_request(_target)?\s*:")
        self.assertIn("branches: [main]", self.txt)
        for pasta in ("base", "fontes", "modelos", "build", "pd", "docs"):
            self.assertIn(f'"{pasta}/**"', self.txt)

    def test_permissoes_minimas(self):
        self.assertEqual(_permissoes_do_topo(self.txt), {"contents": "read", "pages": "write", "id-token": "write"})
        self.assertNotRegex(self.txt, r"write-all|contents:\s*write")

    def test_sem_entrada_do_usuario_em_run(self):
        blocos = _blocos_run(self.txt)
        self.assertGreaterEqual(len(blocos), 2)
        for b in blocos:
            self.assertNotIn("${{", b)

    def test_sem_segredos(self):
        self.assertNotIn("secrets.", self.txt)

    def test_versoes_fixadas(self):
        usos = re.findall(r"(?m)^\s*(?:- )?uses:\s*(\S+)", self.txt)
        for u in usos:
            self.assertRegex(u, r"^actions/[\w-]+@v\d+$")
        for a in ("actions/checkout@v4", "actions/setup-python@v5", "actions/upload-pages-artifact@v3",
                  "actions/deploy-pages@v4"):
            self.assertIn(a, usos)

    def test_concorrencia_e_passos(self):
        self.assertRegex(self.txt, r"concurrency:\n\s+group: pages")
        self.assertIn("ref: ${{ inputs.ref }}", self.txt)
        self.assertIn("build/gerar_site.py", self.txt)
        self.assertIn("--verificar", self.txt)
        self.assertIn("name: github-pages", self.txt)


class TestGitignoreDoSite(unittest.TestCase):
    """O site gerado fica fora do git; as fontes de docs/ continuam versionadas."""

    def test_gitignore(self):
        linhas = set((RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines())
        for x in ("/docs/index.html", "/docs/404.html", "/docs/opensearch.xml", "/docs/robots.txt",
                  "/docs/sitemap*.xml", "/docs/.gerado", "/docs/dados/", "/docs/cf/"):
            self.assertIn(x, linhas)
        for tsig in ("lei", "lc", "dl", "mp", "ec", "ld", "ecr"):
            self.assertIn(f"/docs/{tsig}/", linhas)
        for ln in linhas:
            self.assertNotIn(ln.strip().strip("/"), ("docs", "docs/*", "docs/**", "docs/assets",
                                                     "docs/config.js", "docs/.nojekyll", "docs/favicon.svg"))


class TestFumaca(unittest.TestCase):
    def test_help_de_outra_pasta(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-P", "-B", str(RAIZ / "atualizador" / "atualizar.py"), "--help"],
                               cwd=tmp, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--offline-cache-raiz", r.stdout)


if __name__ == "__main__":
    unittest.main()
