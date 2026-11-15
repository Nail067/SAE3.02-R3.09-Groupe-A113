"""Tests de la configuration partagée (common/config.py)."""
import os
import tempfile
import unittest
from pathlib import Path

from common.config import DEFAULTS, load


class ConfigTest(unittest.TestCase):
    """Ordre de priorité des sources de configuration et absence de secret dans le dépôt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / "deploy").mkdir()
        self.saved = {k: v for k, v in os.environ.items() if k.startswith("CARREFOUR_")}
        for k in self.saved:
            del os.environ[k]

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith("CARREFOUR_")]:
            del os.environ[k]
        os.environ.update(self.saved)
        self.tmp.cleanup()

    def ecrire(self, nom, texte):
        """Écrit un fichier de configuration dans le dossier deploy/ temporaire."""
        (Path(self.tmp.name) / "deploy" / nom).write_text(texte, encoding="utf-8")

    def test_defaults_sans_fichier(self):
        self.assertEqual(load(Path(self.tmp.name))["IP_DATABASE"], DEFAULTS["IP_DATABASE"])

    def test_fichier_et_commentaires(self):
        self.ecrire("carrefour.conf", "# commentaire\nIP_DATABASE=10.1.1.2\n\nTOKEN=abc\n")
        cfg = load(Path(self.tmp.name))
        self.assertEqual((cfg["IP_DATABASE"], cfg["TOKEN"]), ("10.1.1.2", "abc"))

    def test_local_surcharge_le_depot(self):
        self.ecrire("carrefour.conf", "TOKEN=depot\n")
        self.ecrire("carrefour.local.conf", "TOKEN=local\n")
        self.assertEqual(load(Path(self.tmp.name))["TOKEN"], "local")

    def test_environnement_prioritaire_et_alias_host(self):
        self.ecrire("carrefour.conf", "TOKEN=depot\n")
        os.environ["CARREFOUR_TOKEN"] = "env"
        os.environ["CARREFOUR_HOST"] = "127.0.0.1"
        cfg = load(Path(self.tmp.name))
        self.assertEqual((cfg["TOKEN"], cfg["IP_SERVEUR_CLIENTS"]), ("env", "127.0.0.1"))


    def test_espaces_ignores_dans_les_variables(self):
        os.environ["CARREFOUR_HOST"] = "10.0.0.6 "      # cas de « set X=... && » sous Windows
        self.assertEqual(load(Path(self.tmp.name))["IP_SERVEUR_CLIENTS"], "10.0.0.6")

    def test_aucun_secret_dans_le_depot(self):
        cfg = load(Path(__file__).resolve().parent.parent)
        if not (Path(__file__).resolve().parent.parent / "deploy" / "carrefour.local.conf").exists():
            self.assertEqual((cfg["DB_PASSWORD"], cfg["TOKEN"]), ("", ""))
        self.assertEqual((DEFAULTS["DB_PASSWORD"], DEFAULTS["TOKEN"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
