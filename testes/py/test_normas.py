import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import unittest  # noqa: E402

from pd import normas as nor  # noqa: E402
from pd import ordem  # noqa: E402

P = "https://www.planalto.gov.br/ccivil_03/"


class TestAno(unittest.TestCase):
    def test_data_nula(self):
        self.assertEqual(nor.ano_de("5.167-A, de 123.1.27", None, P + "leis/1901-1929/L5167A.htm",
                                    P + "leis/QUADRO/anterior_1960.htm", 2026), 1927)
        self.assertEqual(nor.ano_de("1.273, d e 29.5.73", None, P + "Decreto-Lei/1965-1988/Del1273.htm",
                                    P + "Decreto-Lei/1965-1988/_quadro.htm", 2026), 1973)
        self.assertEqual(nor.ano_de("3.171, de 3.4..41", None, P + "Decreto-Lei/1937-1946/Del3171.htm",
                                    P + "Decreto-Lei/1937-1946/_quadro.htm", 2026), 1941)

    def test_anterior_1960_quatro_digitos(self):
        self.assertEqual(nor.ano_de("1.234, de 5.6.1890", "de 5.6.1890", P + "leis/1851-1900/L1234.htm",
                                    P + "leis/QUADRO/anterior_1960.htm", 2026), 1890)
        self.assertEqual(nor.ano_de("3.698, de 18.12.59", "de 18.12.59", P + "leis/1950-1969/L3698.htm",
                                    P + "leis/QUADRO/anterior_1960.htm", 2026), 1959)

    def test_lc_1(self):
        q = P + "LEIS/LCP/Quadro_Lcp.htm"
        self.assertEqual(nor.ano_de("Lei complementar nº 1, de 17.7.1962", "de 17.7.1962",
                                    P + "LEIS/LCP/Lcp01-62.htm", q, 2026), 1962)
        self.assertEqual(nor.ano_de("Lei Complementar nº 1, de 9.11.1967", "de 9.11.1967",
                                    P + "LEIS/LCP/Lcp01.htm", q, 2026), 1967)

    def test_mp_10(self):
        self.assertEqual(nor.ano_de("10, de 3.11.1988", "de 3.11.1988", P + "MPV/1988-1989/010.htm",
                                    P + "MPV/Quadro/QuadroANT1988-1991.htm", 2026), 1988)
        self.assertEqual(nor.ano_de("10, de 13.11.2001", "de 13.11.2001", P + "MPV/Antigas_2001/10.htm",
                                    P + "MPV/Quadro/_Quadro2001-2002.htm", 2026), 2001)

    def test_bucket_de_um_ano_manda(self):
        self.assertEqual(nor.ano_de("1, de 1.1.99", "de 1.1.99", P + "leis/L1.htm", P + "leis/QUADRO/1990.htm", 2026), 1990)

    def test_sem_ano(self):
        with self.assertRaises(nor.ErroAno):
            nor.ano_de("sem data", None, P + "leis/L1.htm", P + "leis/_desconhecido.htm", 2026)

    def test_resolver(self):
        self.assertIsNone(nor.resolver_ano(5, (1800, 2100)))
        self.assertEqual(nor.resolver_ano(5, (1962, 2026)), 2005)
        self.assertIsNone(nor.resolver_ano(150, (1900, 2000)))
        self.assertIsNone(nor.resolver_ano(None, (1900, 2000)))


class TestLetraChave(unittest.TestCase):
    def test_letra_pelo_rotulo(self):
        self.assertEqual(nor.letra_de("lei", "", "3.890-A, de 25.4.61", P + "leis/L3890Acons.htm"), "a")

    def test_letra_pelo_sufixo(self):
        self.assertEqual(nor.letra_de("lei", "a", "5.467-A, de 6.7.68", P + "leis/1950-1969/L5467-A.htm"), "a")

    def test_letra_pelo_arquivo(self):
        self.assertEqual(nor.letra_de("lei", "", "9.999, de 1.1.70", P + "leis/L9999Bcons.htm"), "b")
        self.assertEqual(nor.letra_de("lei", "", "8.036, de 11.5.90", P + "leis/L8036consol.htm"), "")
        self.assertEqual(nor.letra_de("lei", "", "13.105", P + "x/L13105compilada.htm"), "")

    def test_mp_reed(self):
        self.assertEqual(nor.letra_de("medida provisoria", "-35", "2.158-35, de 24.8.2001", P + "MPV/2158-35.htm"), "")
        self.assertEqual(nor.reed_de("medida provisoria", "-35"), "35")
        self.assertEqual(nor.reed_de("lei", "-35"), "")

    def test_chave(self):
        self.assertEqual(nor.chave("lei", 5467, "a", 1968), "lei-5467a-1968")
        self.assertEqual(nor.chave("dl", 5452, "", 1943), "dl-5452-1943")
        self.assertEqual(nor.chave("cf", 1988, "", 1988), "cf-1988")


class TestEmenta(unittest.TestCase):
    BASE = "Dispõe sobre x e dá outras providências."

    def test_vetos(self):
        for cauda in (" Mensagem de veto", " Mensagem de Veto", " Mensagem de Veto nº 927", " Mensagem de veto.",
                      " (Mensagem de veto)", " Mensagem de Veto ao Projeto de Lei nº 12"):
            self.assertEqual(nor.limpar_ementa(self.BASE + cauda, "lei"), self.BASE, cauda)

    def test_mp_status(self):
        self.assertEqual(nor.limpar_ementa(self.BASE + " Revogada Revogada pela Lei nº 1, de 2000", "medida provisoria"),
                         self.BASE)
        self.assertEqual(nor.limpar_ementa(self.BASE + " SEM EFICÁCIA", "medida provisoria"), self.BASE)
        self.assertEqual(nor.limpar_ementa(self.BASE + " Convertida na Lei nº 9.000, de 1995", "medida provisoria"),
                         self.BASE)

    def test_mp_so_status(self):
        for e in ("Vigência encerrada Ato Declaratório nº 001, de 2016", "Convertida Lei nº 13.259, de 2016",
                  "Vigência encerrada Ato Declaratório, de 2018"):
            self.assertEqual(nor.limpar_ementa(e, "medida provisoria"), "")

    def test_prejudicados_preservado(self):
        e = "Dispõe sobre os atos prejudicados pela greve e dá outras providências."
        self.assertEqual(nor.limpar_ementa(e, "medida provisoria"), e)

    def test_status_fora_de_mp_nao_corta(self):
        e = self.BASE + " Revogada"
        self.assertEqual(nor.limpar_ementa(e, "lei"), e)

    def test_c1(self):
        self.assertEqual(nor.limpar_ementa("\x93texto\x94", "lei"), "“texto”")
        self.assertEqual(nor.limpar_ementa("a\x81b�", "lei"), "ab")

    def test_espacos_e_vazio(self):
        self.assertEqual(nor.limpar_ementa("  a    b ;, ", "lei"), "a b")
        self.assertEqual(nor.limpar_ementa(None, "lei"), "")

    def test_gates(self):
        self.assertEqual(nor.problemas_ementa(self.BASE, "medida provisoria"), [])
        self.assertTrue(nor.problemas_ementa("x revogadas y", "lei", "lei-1-2000"))
        self.assertEqual(nor.problemas_ementa("x revogadas y", "lei", "lei-1346-1951"), [])


class TestDataNome(unittest.TestCase):
    def test_data(self):
        self.assertEqual(nor.data_iso("de 11.5.90", None, 1990), "1990-05-11")
        self.assertEqual(nor.data_iso("de 1º de março de 2001", None, 2001), "2001-03-01")
        self.assertEqual(nor.data_iso("de 31.2.90", None, 1990), "")
        self.assertEqual(nor.data_iso(None, None, 1990), "")

    def test_nome(self):
        self.assertEqual(nor.nome_norma("lei", 8036, "", "", 1990), "Lei nº 8.036/1990")
        self.assertEqual(nor.nome_norma("dl", 5452, "", "", 1943), "Decreto-Lei nº 5.452/1943")
        self.assertEqual(nor.nome_norma("lei", 5467, "a", "", 1968), "Lei nº 5.467-A/1968")
        self.assertEqual(nor.nome_norma("mp", 2158, "", "35", 2001), "Medida Provisória nº 2.158-35/2001")
        self.assertEqual(nor.nome_norma("cf", 1988, "", "", 1988), "Constituição Federal de 1988")

    def test_caminho_relativo(self):
        self.assertEqual(nor.caminho_relativo("https://www.planalto.gov.br/ccivil_03/Leis/L1.htm"), "Leis/L1.htm")
        with self.assertRaises(ValueError):
            nor.caminho_relativo("https://exemplo.org/x.htm")


class TestOrdem(unittest.TestCase):
    def test_ordem_chave(self):
        ks = ["cf-1988", "lei-10-1990", "dl-5452-1943", "lei-9-2000", "lei-5467a-1968", "lei-5467-1968"]
        self.assertEqual(sorted(ks, key=ordem.ordem_chave),
                         ["lei-9-2000", "lei-10-1990", "lei-5467-1968", "lei-5467a-1968", "dl-5452-1943", "cf-1988"])

    def test_ordem_publica(self):
        g = ["lei-5452-1968", "dl-5452-1943"]
        self.assertEqual(ordem.ordem_publica(g, set()), ["lei-5452-1968", "dl-5452-1943"])
        self.assertEqual(ordem.ordem_publica(g, {"dl-5452-1943"}), ["dl-5452-1943", "lei-5452-1968"])
        self.assertEqual(ordem.ordem_publica([{"k": "mp-100-1989", "a": 1989}, {"k": "mp-100-2002", "a": 2002}]),
                         [{"k": "mp-100-2002", "a": 2002}, {"k": "mp-100-1989", "a": 1989}])

    def test_ordem_grupo(self):
        gs = ["lei:9991", "num:9993", "dl:1", "num:9992"]
        self.assertEqual(sorted(gs, key=ordem.ordem_grupo), ["num:9992", "num:9993", "lei:9991", "dl:1"])


if __name__ == "__main__":
    unittest.main()
