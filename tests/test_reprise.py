"""Journalisation sans perte : reprise après coupure réseau, renvois ignorés, redémarrage du serveur, panne de base."""
import os
import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from client.outbox import Outbox
from common.protocol import FrameBuffer, encode
from run_demo import port_libre
from server.server import IntersectionServer

PARAMS = {"type_carrefour": "4 branches", "regulation": "feux", "densite": 5}


def il_y_a(secondes):
    """Horodatage au format du protocole, `secondes` dans le passé."""
    return (datetime.now() - timedelta(seconds=secondes)).strftime("%Y-%m-%d %H:%M:%S")


class Poste:
    """Client minimal (comme l'IHM) : se connecte, s'authentifie, envoie des lots et lit les réponses."""

    def __init__(self, port):
        """Ouvre la connexion et s'authentifie."""
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.buf = FrameBuffer()
        self.envoyer({"type": "hello", "client": "IHM-test"})
        self.attendre("welcome")

    def envoyer(self, msg):
        """Envoie un message JSON."""
        self.sock.sendall(encode(msg))

    def attendre(self, type_msg, delai=3.0):
        """Renvoie le premier message reçu du type demandé (None après `delai`)."""
        fin = time.time() + delai
        while time.time() < fin:
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not data:
                return None
            for msg in self.buf.feed(data):
                if msg.get("type") == type_msg:
                    return msg
        return None

    def lot(self, sess, messages, params=None):
        """Envoie un lot et renvoie le numéro acquitté."""
        self.envoyer({"type": "batch", "messages": messages, "sessions": {sess: params or PARAMS}})
        while True:
            ack = self.attendre("ack")
            if ack is None or ack.get("ref") == "batch":   # (crossing_done a aussi son propre acquittement)
                return ack.get("n") if ack else None

    def fermer(self):
        """Coupe la connexion (comme une coupure réseau)."""
        self.sock.close()


class RepriseTest(unittest.TestCase):
    """Le serveur ne perd ni ne duplique rien quand l'IHM se reconnecte et renvoie sa file d'attente."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"SQLITE_PATH": os.path.join(self.tmp.name, "t.db"), "CARREFOUR_TOKEN": ""})
        self.env.start()
        os.environ.pop("DB_HOST", None)
        self.demarrer()

    def demarrer(self):
        """Lance un serveur sur un port libre, dans un thread."""
        self.port = port_libre(5300)
        self.srv = IntersectionServer("127.0.0.1", self.port)
        self.thread = threading.Thread(target=self.srv.run, daemon=True)
        self.thread.start()

    def arreter(self):
        """Arrête le serveur (comme un redémarrage du service)."""
        self.srv.stop()
        self.thread.join(5)
        self.srv.db.conn.close()

    def tearDown(self):
        self.arreter()
        self.env.stop()
        self.tmp.cleanup()

    def sql(self, requete, params=()):
        """Exécute une requête de lecture sur la base du serveur."""
        return self.srv.db._run(requete, params, fetch=True)[1]

    def test_coupure_puis_reprise_sans_perte_ni_doublon(self):
        p = Poste(self.port)
        self.assertEqual(p.lot("K1", [
            {"n": 1, "sess": "K1", "type": "session_start", **PARAMS, "ts": il_y_a(60)},
            {"n": 2, "sess": "K1", "type": "vehicle", "vid": 7, "kind": "ambulance", "direction": "Nord", "ts": il_y_a(59)},
        ]), 2)
        p.fermer()                                    # coupure : la session est fermée provisoirement
        time.sleep(0.3)
        self.assertIsNotNone(self.sql("SELECT date_fin FROM sessions_simulation")[0][0])

        hors_ligne = [   # événements survenus pendant la coupure, envoyés à la reconnexion
            {"n": 3, "sess": "K1", "type": "priority_log", "resultat": "mode dégradé", "approach": "Nord", "vid": 7, "rid": 1,
             "ts": il_y_a(40)},
            {"n": 4, "sess": "K1", "type": "light_change", "feu": "Nord", "etat": "vert", "cause": "priorité urgence",
             "ts": il_y_a(40)},
            {"n": 5, "sess": "K1", "type": "crossing_done", "vehicle": "Ambulance", "vid": 7, "rid": 1, "duration": 6.5,
             "ts": il_y_a(34)},
        ]
        p = Poste(self.port)
        self.assertEqual(p.lot("K1", hors_ligne), 5)
        self.assertEqual(p.lot("K1", hors_ligne), 5)  # renvoi (acquittement perdu) : ignoré

        sessions = self.sql("SELECT id_session, date_fin FROM sessions_simulation")
        self.assertEqual(len(sessions), 1)            # la même session continue
        self.assertIsNone(sessions[0][1])             # rouverte à la reconnexion
        prio = self.sql("SELECT heure_demande, resultat, duree_s, id_vehicule FROM evenements_priorite")
        self.assertEqual(len(prio), 1)
        self.assertEqual(prio[0][0], hors_ligne[0]["ts"])    # heure réelle, pas l'heure de réception
        self.assertEqual((prio[0][1], prio[0][2]), ("mode dégradé", 6.5))
        self.assertIsNotNone(prio[0][3])              # rattachée au véhicule créé avant la coupure
        self.assertEqual(len(self.sql("SELECT * FROM journal_feux")), 1)
        self.assertEqual(len(self.sql("SELECT * FROM evenements_trafic WHERE type_evenement = 'passage terminé'")), 1)

        self.assertEqual(p.lot("K1", [{"n": 6, "sess": "K1", "type": "session_end", "ts": il_y_a(30)}]), 6)
        self.assertEqual(self.sql("SELECT date_fin FROM sessions_simulation")[0][0], il_y_a(30))
        p.fermer()

    def test_redemarrage_du_serveur(self):
        p = Poste(self.port)
        p.lot("K2", [{"n": 1, "sess": "K2", "type": "session_start", **PARAMS, "ts": il_y_a(20)}])
        p.fermer()
        self.arreter()
        self.demarrer()                               # mémoire du serveur perdue, base conservée
        p = Poste(self.port)
        self.assertEqual(p.lot("K2", [{"n": 2, "sess": "K2", "type": "traffic_event", "event": "embouteillage détecté",
                                       "details": "file Nord", "ts": il_y_a(5)}]), 2)
        self.assertEqual(len(self.sql("SELECT * FROM sessions_simulation")), 1)   # retrouvée, pas recréée
        self.assertEqual(len(self.sql("SELECT * FROM evenements_trafic")), 1)
        p.fermer()

    def test_session_inconnue_recreee_avec_ses_parametres(self):
        p = Poste(self.port)   # session_start perdu : le lot porte les paramètres de la session
        self.assertEqual(p.lot("K3", [{"n": 9, "sess": "K3", "type": "light_change", "feu": "Est", "etat": "rouge",
                                       "cause": "cycle normal", "ts": il_y_a(3)}], dict(PARAMS, debut=il_y_a(10))), 9)
        self.assertEqual(self.sql("SELECT date_debut, type_carrefour FROM sessions_simulation")[0], [il_y_a(10), "4 branches"])
        p.fermer()

    def test_base_en_panne_le_lot_n_est_pas_acquitte(self):
        p = Poste(self.port)
        p.lot("K4", [{"n": 1, "sess": "K4", "type": "session_start", **PARAMS}])
        with patch.object(self.srv.db, "add_light_log", side_effect=RuntimeError("panne")), \
                patch.object(self.srv.db, "alive", return_value=False):
            n = p.lot("K4", [{"n": 2, "sess": "K4", "type": "vehicle", "vid": 1, "kind": "voiture", "direction": "Sud"},
                             {"n": 3, "sess": "K4", "type": "light_change", "feu": "Sud", "etat": "vert", "cause": "cycle normal"}])
        self.assertEqual(n, 2)                        # le n°3 sera renvoyé par l'IHM
        self.assertEqual(p.lot("K4", [{"n": 3, "sess": "K4", "type": "light_change", "feu": "Sud", "etat": "vert",
                                       "cause": "cycle normal"}]), 3)
        self.assertEqual(len(self.sql("SELECT * FROM journal_feux")), 1)
        p.fermer()

    def test_priorite_accordee_pendant_une_panne_de_base(self):
        p = Poste(self.port)
        p.lot("K6", [{"n": 1, "sess": "K6", "type": "session_start", **PARAMS}])
        heure = il_y_a(8)
        with patch.object(self.srv.db, "add_priority", side_effect=RuntimeError("panne")):
            p.envoyer({"type": "priority_request", "sess": "K6", "vehicle": "Pompiers", "approach": "Sud", "rid": 3})
            self.assertFalse(p.attendre("priority_grant")["logged"])   # accordée quand même, non journalisée
        self.assertEqual(p.lot("K6", [{"n": 2, "sess": "K6", "type": "priority_log", "resultat": "accordée", "approach": "Sud",
                                       "rid": 3, "ts": heure},
                                      {"n": 3, "sess": "K6", "type": "crossing_done", "rid": 3, "duration": 4.0}]), 3)
        self.assertEqual(self.sql("SELECT heure_demande, resultat, duree_s FROM evenements_priorite"), [[heure, "terminée", 4.0]])
        p.fermer()

    def test_priorite_accordee_base_injoignable_session_inconnue(self):
        p = Poste(self.port)   # base en panne avant même que la session ait pu être créée
        with patch.object(self.srv.db, "find_session", side_effect=RuntimeError("panne")), \
                patch.object(self.srv.db, "start_session", side_effect=RuntimeError("panne")), \
                patch.object(self.srv.db, "alive", return_value=False):
            self.assertIsNone(p.lot("K7", [{"n": 1, "sess": "K7", "type": "session_start", **PARAMS}]))
            debut = time.time()
            p.envoyer({"type": "priority_request", "sess": "K7", "vehicle": "Police", "approach": "Ouest", "rid": 9})
            grant = p.attendre("priority_grant")
        self.assertIsNotNone(grant)                   # la priorité est accordée malgré tout…
        self.assertFalse(grant["logged"])             # … sans être journalisée (l'IHM la mettra en file)
        self.assertLess(time.time() - debut, 1.0)
        p.fermer()

    def test_message_invalide_ignore_sans_bloquer_la_file(self):
        p = Poste(self.port)
        p.lot("K5", [{"n": 1, "sess": "K5", "type": "session_start", **PARAMS}])
        n = p.lot("K5", [{"n": 2, "sess": "K5", "type": "crossing_done", "duration": "pas un nombre", "rid": None},
                         {"n": 3, "sess": "K5", "type": "vehicle", "vid": 4, "kind": "bus", "direction": "Est"}])
        self.assertEqual(n, 3)
        self.assertEqual(len(self.sql("SELECT * FROM vehicules")), 1)
        p.fermer()

    def test_ancien_protocole_sans_session(self):
        p = Poste(self.port)   # comme scripts/check_server.py : messages sans `sess` ni `n`
        p.envoyer({"type": "session_start", **PARAMS})
        self.assertIsNotNone(p.attendre("session_started"))
        p.envoyer({"type": "priority_request", "vehicle": "Police", "approach": "Est", "rid": 1})
        self.assertTrue(p.attendre("priority_grant")["logged"])
        p.fermer()


class OutboxTest(unittest.TestCase):
    """File d'attente locale de l'IHM."""

    def test_conservation_acquittement_et_persistance(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "attente.db")
            o = Outbox(chemin)
            o.ajouter_session("S", PARAMS)
            n1 = o.ajouter({"type": "vehicle", "sess": "S", "vid": 1})
            n2 = o.ajouter({"type": "vehicle", "sess": "S", "vid": 2})
            o.valider()
            o.fermer()
            o = Outbox(chemin)                        # IHM relancée : rien n'est perdu
            messages, sessions = o.a_envoyer()
            self.assertEqual([m["n"] for m in messages], [n1, n2])
            self.assertEqual(sessions, {"S": PARAMS})
            self.assertEqual([m["n"] for m in o.a_envoyer(apres=n1)[0]], [n2])
            o.acquitter(n1)
            self.assertEqual(o.nombre(), 1)
            n3 = o.ajouter({"type": "vehicle", "sess": "S", "vid": 3})
            self.assertGreater(n3, n2)                # numéros jamais réutilisés
            o.fermer()


if __name__ == "__main__":
    unittest.main()
