import os
import tempfile
import unittest
from unittest.mock import patch

from server.database import Database


class DatabaseTests(unittest.TestCase):
    """Opérations principales de la couche base de données, sur une base SQLite temporaire."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.env = patch.dict(os.environ, {"SQLITE_PATH": self.db_path}, clear=False)
        self.env.start()
        os.environ.pop("DB_HOST", None)
        self.db = Database()

    def tearDown(self):
        self.db.conn.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def test_session_and_history(self):
        session_id = self.db.start_session("4 branches", "feux", 5, "test")
        columns, rows = self.db.history("sessions_simulation")
        self.assertIn("id_session", columns)
        self.assertEqual(rows[0][0], session_id)
        self.assertEqual(rows[0][3], "4 branches")

    def test_vehicle_and_traffic_event(self):
        session_id = self.db.start_session("T", "feux", 3, "test")
        vehicle_id = self.db.add_vehicle(session_id, "ambulance", "Nord")
        self.db.add_traffic_event(session_id, vehicle_id, "passage terminé", "test")
        columns, rows = self.db.history("evenements_trafic")
        self.assertIn("type_evenement", columns)
        self.assertEqual(rows[0][4], "passage terminé")

    def test_history_rejects_unknown_table(self):
        with self.assertRaises(ValueError):
            self.db.history("table_inconnue")


if __name__ == "__main__":
    unittest.main()
