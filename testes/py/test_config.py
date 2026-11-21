import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import os  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

from pd import config  # noqa: E402

MODELO = """// Planalto Direto — configuração. Edite só os valores entre aspas.
window.PD_CONFIG = Object.freeze({
  PLANALTO_BASE: "https://www.planalto.gov.br/ccivil_03/",
  SITE_URL: "https://exemplo.github.io/planalto-direto/",
  SITE_PATH: "/planalto-direto/",
  REPO_URL: "https://github.com/exemplo/planalto-direto",
  SUGESTAO_ATIVA: "sim",
  SUGESTAO_URL: "",
  SUGESTAO_CAMPO: "",
  GOOGLE_VERIFICACAO: "",
  ESPERA_MS: "1200",
  ESPERA_DICA_MS: "3000"
});
"""


class TestConfig(unittest.TestCase):
    def ler(self, texto):
        fd, p = tempfile.mkstemp(suffix=".js")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(texto)
            return config.ler_config(p)
        finally:
            os.unlink(p)

    def test_real(self):
        cfg = config.ler_config()
        self.assertEqual(set(cfg), set(config.CHAVES))
        self.assertTrue(cfg["SITE_URL"].endswith(cfg["SITE_PATH"]))

    def test_sem_login_no_config(self):
        # SITE_URL/REPO_URL ficam vazios no repo: nenhum nome de usuario no codigo
        texto = (config.RAIZ / "docs" / "config.js").read_text(encoding="utf-8")
        self.assertIn('SITE_URL: "",', texto)
        self.assertIn('REPO_URL: "",', texto)

    def test_urls_do_ambiente(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"PD_SITE_URL": "", "PD_REPO_URL": "", "GITHUB_REPOSITORY": "Dono/planalto-direto",
                                          "GITHUB_SERVER_URL": "https://github.com"}):
            self.assertEqual(config.urls_do_ambiente(), ("https://dono.github.io/planalto-direto/",
                                                          "https://github.com/Dono/planalto-direto"))
        with mock.patch.dict(os.environ, {"PD_SITE_URL": "https://x.example/planalto-direto", "GITHUB_REPOSITORY": ""}):
            self.assertEqual(config.urls_do_ambiente()[0], "https://x.example/planalto-direto/")
        with mock.patch.dict(os.environ, {"PD_SITE_URL": "", "PD_REPO_URL": "", "GITHUB_REPOSITORY": ""}):
            self.assertEqual(config.urls_do_ambiente(), ("https://exemplo.invalid/planalto-direto/", ""))

    def test_modelo(self):
        cfg = self.ler(MODELO)
        self.assertEqual(cfg["ESPERA_MS"], "1200")
        self.assertEqual(cfg["SITE_PATH"], "/planalto-direto/")

    def test_chave_faltando(self):
        texto = "\n".join(l for l in MODELO.splitlines() if "REPO_URL" not in l)
        with self.assertRaises(config.ErroConfig):
            self.ler(texto)

    def test_chave_repetida(self):
        texto = MODELO.replace('  ESPERA_MS: "1200",', '  ESPERA_MS: "1200",\n  ESPERA_MS: "1300",')
        with self.assertRaises(config.ErroConfig):
            self.ler(texto)

    def test_site_path_incoerente(self):
        with self.assertRaises(config.ErroConfig):
            self.ler(MODELO.replace('SITE_PATH: "/planalto-direto/"', 'SITE_PATH: "/outro/"'))
        with self.assertRaises(config.ErroConfig):
            self.ler(MODELO.replace('SITE_PATH: "/planalto-direto/"', 'SITE_PATH: "planalto-direto/"'))

    def test_validacoes(self):
        with self.assertRaises(config.ErroConfig):
            self.ler(MODELO.replace("https://www.planalto.gov.br/ccivil_03/", "http://www.planalto.gov.br/ccivil_03/"))
        with self.assertRaises(config.ErroConfig):
            self.ler(MODELO.replace('SUGESTAO_CAMPO: ""', 'SUGESTAO_CAMPO: "campo1"'))
        with self.assertRaises(config.ErroConfig):
            self.ler(MODELO.replace('SUGESTAO_URL: ""', 'SUGESTAO_URL: "https://exemplo.org/f"'))
        cfg = self.ler(MODELO.replace('SUGESTAO_CAMPO: ""', 'SUGESTAO_CAMPO: "entry.123"'))
        self.assertEqual(cfg["SUGESTAO_CAMPO"], "entry.123")
        with self.assertRaises(config.ErroConfig):
            self.ler(MODELO.replace('SUGESTAO_ATIVA: "sim"', 'SUGESTAO_ATIVA: "talvez"'))
        cfg = self.ler(MODELO.replace('SUGESTAO_ATIVA: "sim"', 'SUGESTAO_ATIVA: "nao"'))
        self.assertEqual(cfg["SUGESTAO_ATIVA"], "nao")


if __name__ == "__main__":
    unittest.main()
