"""Tests du lanceur de démonstration (run_demo.py)."""
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import run_demo


class DemoTest(unittest.TestCase):
    """Lanceur : choix du port, attente du serveur, dossier de données et mémorisation de la VM."""

    def test_port_libre_evite_un_port_occupe(self):
        with socket.socket() as occupe:
            occupe.bind(("127.0.0.1", 0))
            port = occupe.getsockname()[1]
            self.assertNotEqual(run_demo.port_libre(port), port)

    def test_attendre_detecte_un_serveur(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        threading.Thread(target=lambda: srv.accept(), daemon=True).start()
        self.assertTrue(run_demo.attendre(port, delai=3))
        srv.close()

    def test_attendre_echoue_sans_serveur(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            libre = s.getsockname()[1]
        self.assertFalse(run_demo.attendre(libre, delai=0.6))

    def test_donnees_dans_le_projet_si_inscriptible(self):
        self.assertEqual(run_demo.dossier_donnees(), run_demo.ROOT / "donnees")

    def test_donnees_dans_le_dossier_temporaire_si_projet_en_lecture_seule(self):
        with mock.patch("os.access", return_value=False):
            dossier = run_demo.dossier_donnees()
        self.assertEqual(dossier.name, "carrefour-donnees")
        self.assertNotEqual(dossier.parent, run_demo.ROOT)


    def test_memoriser_conserve_les_autres_lignes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "carrefour.local.conf"
            f.write_text("IP_DATABASE=10.1.1.2\nTOKEN=ancien\n", encoding="utf-8")
            run_demo.memoriser("10.0.0.6", "nouveau", f)
            texte = f.read_text(encoding="utf-8")
        self.assertIn("IP_DATABASE=10.1.1.2", texte)
        self.assertIn("IP_SERVEUR_CLIENTS=10.0.0.6", texte)
        self.assertIn("TOKEN=nouveau", texte)
        self.assertNotIn("ancien", texte)


if __name__ == "__main__":
    unittest.main()
