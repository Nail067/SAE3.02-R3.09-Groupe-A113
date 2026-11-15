"""File d'attente locale des événements à journaliser (SQLite sur le poste IHM) : aucune perte si le serveur est coupé.

Chaque événement (session, véhicules, feux, priorités, passages) est d'abord écrit ici avec un numéro croissant `n`,
sa session `sess` et son heure réelle `ts`, puis envoyé au serveur par lots. Il n'est supprimé qu'une fois acquitté
par le serveur ({"type": "ack", "ref": "batch", "n": ...}). Le fichier survit à la fermeture de l'IHM : les
événements non transmis partent à la connexion suivante.

Utilisé uniquement depuis le thread de l'IHM (pas de partage entre threads).
"""
import json
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("carrefour.outbox")
TAILLE_MAX = 50_000   # au-delà, les plus anciens événements sont abandonnés (coupure de plusieurs heures)


class Outbox:
    """Événements en attente d'acquittement par le serveur, avec les paramètres de leurs sessions."""

    def __init__(self, chemin):
        """Ouvre (ou crée) le fichier de la file ; en cas d'impossibilité, file en mémoire (perdue à la fermeture)."""
        self.chemin = str(chemin)
        try:
            Path(self.chemin).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.chemin)
        except (OSError, sqlite3.Error) as exc:
            log.warning("File d'attente sur disque impossible (%s) : file en mémoire", exc)
            self.chemin = ":memory:"
            self.conn = sqlite3.connect(self.chemin)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("CREATE TABLE IF NOT EXISTS attente (n INTEGER PRIMARY KEY AUTOINCREMENT, sess TEXT, message TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS sessions (sess TEXT PRIMARY KEY, parametres TEXT NOT NULL)")
        self.conn.commit()

    def ajouter_session(self, sess: str, parametres: dict):
        """Mémorise les paramètres d'une session (pour la recréer côté serveur si nécessaire)."""
        self.conn.execute("INSERT OR REPLACE INTO sessions (sess, parametres) VALUES (?, ?)",
                          (sess, json.dumps(parametres, ensure_ascii=False)))

    def ajouter(self, message: dict) -> int:
        """Met un événement en attente et renvoie son numéro (l'écriture sur disque a lieu à `valider`)."""
        cur = self.conn.execute("INSERT INTO attente (sess, message) VALUES (?, ?)",
                                (message.get("sess"), json.dumps(message, ensure_ascii=False)))
        return cur.lastrowid

    def valider(self):
        """Écrit sur disque les ajouts en cours et borne la taille de la file."""
        if self.nombre() > TAILLE_MAX:
            self.conn.execute("DELETE FROM attente WHERE n IN (SELECT n FROM attente ORDER BY n LIMIT ?)", (TAILLE_MAX // 5,))
            log.warning("File d'attente pleine : les plus anciens événements ont été abandonnés")
        self.conn.commit()

    def a_envoyer(self, apres: int = 0, limite: int = 150):
        """Renvoie (messages numérotés, paramètres des sessions concernées) à envoyer, à partir du numéro `apres` exclu."""
        lignes = self.conn.execute("SELECT n, message FROM attente WHERE n > ? ORDER BY n LIMIT ?", (apres, limite)).fetchall()
        messages = []
        for n, texte in lignes:
            msg = json.loads(texte)
            msg["n"] = n
            messages.append(msg)
        cles = sorted({m["sess"] for m in messages if m.get("sess")})
        sessions = {}
        for cle in cles:
            ligne = self.conn.execute("SELECT parametres FROM sessions WHERE sess = ?", (cle,)).fetchone()
            if ligne:
                sessions[cle] = json.loads(ligne[0])
        return messages, sessions

    def acquitter(self, n: int):
        """Supprime les événements enregistrés par le serveur (numéros <= n) ; ne garde que les 50 dernières sessions."""
        self.conn.execute("DELETE FROM attente WHERE n <= ?", (int(n),))
        self.conn.execute("DELETE FROM sessions WHERE rowid NOT IN (SELECT rowid FROM sessions ORDER BY rowid DESC LIMIT 50)"
                          " AND sess NOT IN (SELECT DISTINCT sess FROM attente WHERE sess IS NOT NULL)")
        self.conn.commit()

    def nombre(self) -> int:
        """Nombre d'événements en attente."""
        return self.conn.execute("SELECT COUNT(*) FROM attente").fetchone()[0]

    def fermer(self):
        """Écrit les derniers ajouts et ferme le fichier."""
        try:
            self.conn.commit()
            self.conn.close()
        except sqlite3.Error:
            pass
