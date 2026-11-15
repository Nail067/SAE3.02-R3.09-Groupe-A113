"""Base MariaDB distante injoignable : pas de repli SQLite, échecs rapides, reprise automatique au retour de la base."""
import os
import sqlite3
import sys
import time
import types
import unittest
from unittest.mock import patch

from server import database as dbm


class FauxMariadb(types.ModuleType):
    """Connecteur MariaDB factice : la « base » est joignable ou non selon `en_ligne`."""

    def __init__(self):
        """Base injoignable au départ ; compte les tentatives de connexion."""
        super().__init__("mariadb")
        self.en_ligne, self.tentatives = False, 0

    def connect(self, **_):
        """Renvoie une connexion SQLite en mémoire si la base est en ligne, sinon échoue."""
        self.tentatives += 1
        if not self.en_ligne:
            raise ConnectionError("Can't connect to server on '192.168.56.104'")
        conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        for stmt in dbm.SQLITE_DDL:
            conn.execute(stmt)
        return conn


class BaseDistanteTest(unittest.TestCase):
    """Comportement du serveur quand DB_HOST est défini mais que MariaDB ne répond pas."""

    def setUp(self):
        self.faux = FauxMariadb()
        self.patches = [patch.dict(os.environ, {"DB_HOST": "192.168.56.104"}), patch.dict(sys.modules, {"mariadb": self.faux})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_demarrage_sans_base_puis_retour(self):
        db = dbm.Database()                           # la base distante est éteinte au démarrage du serveur
        self.assertEqual(db.backend, "mariadb")       # pas de repli silencieux sur SQLite
        self.assertIsNone(db.conn)
        debut = time.monotonic()
        for _ in range(3):
            with self.assertRaises(Exception):
                db.start_session("4 branches", "feux", 5)
        self.assertLess(time.monotonic() - debut, 0.5)   # échecs immédiats, le serveur ne se bloque pas
        self.assertEqual(self.faux.tentatives, 1)        # pas de nouvelle tentative avant RETRY_S
        self.assertFalse(db.alive())

        self.faux.en_ligne = True                     # la VM base démarre
        db._retry_after = 0                           # (au lieu d'attendre RETRY_S secondes)
        self.assertTrue(db.alive())
        self.assertIsInstance(db.start_session("4 branches", "feux", 5), int)
        self.assertEqual(db.backend, "mariadb")

    def test_liaison_perdue_puis_reconnexion(self):
        self.faux.en_ligne = True
        db = dbm.Database()
        db.start_session("4 branches", "feux", 5)
        db.conn.close()                               # coupure de la liaison en cours de route
        self.assertIsInstance(db.start_session("rond-point", "giratoire", 3), int)   # reconnexion transparente

    def test_connecteur_absent_repli_sqlite(self):
        with patch.dict(sys.modules, {"mariadb": None}), patch.dict(os.environ, {"SQLITE_PATH": ":memory:"}):
            db = dbm.Database()
        self.assertEqual(db.backend, "sqlite")        # seul cas de repli : système sans connecteur MariaDB


if __name__ == "__main__":
    unittest.main()
