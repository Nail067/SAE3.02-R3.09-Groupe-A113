"""Vérification de bout en bout du serveur et de la base (à lancer depuis n'importe quel poste du réseau).

    python scripts/check_server.py --host <IP_VM_SERVEUR> --token <JETON>   (affichés à la fin de install.sh)

Rejoue le scénario « une ambulance arrive dans un bouchon » puis relit la base via le serveur.
Code de sortie : 0 si tout est conforme, 1 sinon.
"""
import argparse
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import load  # noqa: E402

CFG = load()

OK, KO = "\033[32mOK\033[0m", "\033[31mKO\033[0m"


class Link:
    """Petit client JSON-lignes synchrone."""

    def __init__(self, host, port, timeout=5):
        """Ouvre la connexion TCP vers le serveur."""
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""

    def send(self, msg):
        """Envoie un message JSON terminé par un saut de ligne."""
        self.sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())

    def recv(self, wanted=None, timeout=5):
        """Attend un message (du type `wanted` si précisé) pendant au plus `timeout` secondes ; None sinon."""
        end = time.time() + timeout
        while time.time() < end:
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                msg = json.loads(line)
                if wanted is None or msg.get("type") == wanted:
                    return msg
            self.sock.settimeout(max(0.1, end - time.time()))
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            self.buf += data
        return None


def main():
    """Rejoue un scénario complet contre le serveur et affiche chaque contrôle ; renvoie 0 si tout est conforme."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=CFG["IP_SERVEUR_CLIENTS"])
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--token", default=CFG["TOKEN"])
    ap.add_argument("--accepter-sqlite", action="store_true", help="ne pas exiger MariaDB (repli SQLite accepté)")
    a = ap.parse_args()
    failures = 0

    def check(label, cond, extra=""):
        """Affiche un contrôle OK/KO et compte les échecs ; renvoie la condition."""
        nonlocal failures
        print(f"  [{OK if cond else KO}] {label} {extra}")
        failures += 0 if cond else 1
        return cond

    print(f"Test du serveur {a.host}:{a.port}")
    try:
        link = Link(a.host, a.port)
    except OSError as exc:
        print(f"  [{KO}] connexion TCP impossible : {exc}")
        return 1
    link.send({"type": "hello", "client": "check_server", "token": a.token})
    w = link.recv("welcome")
    check("connexion et authentification", w is not None)
    if not w:
        return 1
    check("base de données", w.get("db") == "mariadb" or (a.accepter_sqlite and w.get("db") == "sqlite"), f"(moteur : {w.get('db')})")
    check("5 tables déclarées", len(w.get("tables", [])) == 5)
    link.send({"type": "session_start", "type_carrefour": "4 branches", "regulation": "feux", "densite": 8})
    s = link.recv("session_started")
    check("ouverture de session", bool(s), f"(id_session={s and s.get('id_session')})")
    link.send({"type": "vehicle", "vid": 1, "kind": "ambulance", "direction": "Nord", "destination": "Sud"})
    link.send({"type": "traffic_event", "vid": 1, "event": "embouteillage détecté", "details": "6 véhicules à l'arrêt, branche Nord"})
    link.send({"type": "priority_request", "vid": 1, "rid": 1, "vehicle": "Ambulance", "approach": "Nord", "destination": "Sud"})
    g = link.recv("priority_grant")
    check("priorité accordée", bool(g) and g.get("approach") == "Nord", f"(axe {g and g.get('axis')})")
    check("demande journalisée en base", bool(g) and g.get("logged") is True)
    link.send({"type": "light_change", "feu": "Nord", "etat": "vert", "cause": "priorité urgence"})
    link.send({"type": "light_change", "feu": "Est", "etat": "rouge", "cause": "priorité urgence"})
    time.sleep(1.2)
    link.send({"type": "crossing_done", "vid": 1, "rid": 1, "vehicle": "Ambulance", "duration": 5.2})
    check("fin de passage acquittée", link.recv("ack") is not None)
    link.send({"type": "light_change", "feu": "Nord", "etat": "vert", "cause": "retour au cycle normal"})
    link.send({"type": "vehicle_state", "vid": 1, "etat": "a franchi le carrefour"})
    time.sleep(0.5)
    for table in ("sessions_simulation", "vehicules", "evenements_priorite", "evenements_trafic", "journal_feux"):
        link.send({"type": "history", "table": table, "limit": 5})
        r = link.recv("history_result")
        check(f"table {table}", bool(r) and len(r.get("rows", [])) >= 1, f"({len(r['rows']) if r else 0} ligne(s) lue(s))")
    link.send({"type": "history", "table": "evenements_priorite", "limit": 1})
    r = link.recv("history_result")
    if r and r["rows"]:
        row = dict(zip(r["columns"], r["rows"][0]))
        check("intervention clôturée (résultat + durée)", row.get("resultat") == "terminée" and row.get("duree_s") == 5.2, f"({row.get('resultat')}, {row.get('duree_s')} s)")
    link.send({"type": "chronology"})
    c = link.recv("history_result")
    check("chronologie de l'intervention", bool(c) and len(c["rows"]) >= 3)
    if c:
        for heure, evt in c["rows"]:
            print(f"        {heure}  {evt}")
    link.send({"type": "history", "table": "table_inconnue"})
    e = link.recv()
    check("table inconnue refusée", bool(e) and e.get("type") == "error")
    link.send({"type": "session_end"})
    print("\nRésultat :", "tout est conforme" if not failures else f"{failures} contrôle(s) en échec")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
