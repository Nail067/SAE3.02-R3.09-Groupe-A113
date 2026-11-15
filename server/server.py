"""Serveur du carrefour connecté (VM Serveur) : sockets TCP bruts + select, journalisation en base.

Lancement :  python -m server.server [--host 0.0.0.0] [--port 5050]
Variables d'environnement : DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME (MariaDB), CARREFOUR_TOKEN (jeton optionnel).

Protocole (JSON, une trame par ligne) :
  client -> serveur : hello, session_start, session_end, vehicle, vehicle_state, priority_request, priority_log,
                      crossing_done, traffic_event, light_change, batch, history, chronology, ping
  serveur -> client : welcome, session_started, priority_grant, v2v_alert, ack, history_result, pong, error

Reprise après coupure (aucune perte) : l'IHM numérote ses messages (`n`), les rattache à une session (`sess`) et les
horodate (`ts`). Le serveur acquitte chaque lot ({"type": "ack", "ref": "batch", "n": dernier numéro enregistré}) ;
tant qu'un message n'est pas acquitté, l'IHM le conserve et le renvoie. Les sessions survivent aux reconnexions
(et à un redémarrage du serveur) ; un message déjà enregistré (n <= dernier n traité) est ignoré.
"""
import argparse
import logging
import os
import select
import signal
import socket
from datetime import datetime

from common.protocol import DEFAULT_PORT, FrameBuffer, encode
from server import database as dbm
from server.database import Database

log = logging.getLogger("carrefour.server")
MAX_BUFFER = 256 * 1024          # octets non décodés tolérés par client
AXIS = {"Nord": "NS", "Sud": "NS", "Est": "EW", "Ouest": "EW"}
SESSIONS_MAX = 500               # sessions gardées en mémoire pour la reprise après coupure
TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def heure_message(msg):
    """Heure réelle d'un événement fournie par l'IHM (`ts`), si elle est valide et plausible (± 2 jours) ; sinon None."""
    ts = msg.get("ts")
    if not isinstance(ts, str):
        return None
    try:
        moment = datetime.strptime(ts, TS_FORMAT)
    except ValueError:
        return None
    return ts if abs((moment - datetime.now()).total_seconds()) < 2 * 86400 else None


class SessionState:
    """État serveur d'une session de simulation, conservé d'une connexion à l'autre (reprise après coupure)."""

    def __init__(self, id_session):
        """Associe à la session en base ses correspondances d'identifiants et son dernier message traité."""
        self.id_session = id_session
        self.vehicles = {}      # identifiant local du véhicule (IHM) -> id_vehicule en base
        self.priorities = {}    # identifiant local de la demande (IHM) -> id_priorite en base
        self.degraded = set()   # demandes décidées localement par l'IHM pendant une coupure (mode dégradé)
        self.last_n = 0         # numéro du dernier message enregistré (les renvois sont ignorés)
        self.open = True        # False : date_fin renseignée suite à une coupure (rouverte à la reconnexion)
        self.ended = False      # True : session terminée par l'IHM (session_end)


class ClientContext:
    """État d'un poste IHM connecté : tampon de lecture, session ouverte, correspondances d'identifiants."""

    def __init__(self, sock, addr):
        """Associe au socket d'un poste IHM son tampon de lecture et son état (authentification, session)."""
        self.sock, self.addr, self.buf = sock, addr, FrameBuffer()
        self.name, self.authenticated = "?", False
        self.session = None     # SessionState courante de ce poste
        self.keys = set()       # clés des sessions utilisées par cette connexion
        self.implicit = f"conn:{id(self)}"   # clé de session des clients sans `sess` (ex. check_server.py)
        self.bytes_pending = 0

    @property
    def id_session(self):
        """Identifiant en base de la session courante (None si aucune)."""
        return self.session.id_session if self.session else None


class IntersectionServer:
    """Reçoit les messages V2I/V2V, répond aux demandes de priorité et historise tout en base."""

    def __init__(self, host: str, port: int):
        """Ouvre la base de données puis le socket d'écoute TCP sur host:port."""
        self.db = Database()
        self.token = os.environ.get("CARREFOUR_TOKEN", "")
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((host, port))
        self.srv.listen(16)
        self.clients = {}       # socket -> ClientContext
        self.sessions = {}      # clé de session -> SessionState (survit aux reconnexions)
        self.running = True
        log.info("Écoute sur %s:%d (base : %s, jeton : %s)", host, port, self.db.backend, "oui" if self.token else "non")

    # ------------------------------------------------------------------ boucle principale
    def run(self):
        """Boucle d'E/S multiplexée (select)."""
        while self.running:
            readable, _, _ = select.select([self.srv, *self.clients], [], [], 1.0)
            for sock in readable:
                if sock is self.srv:
                    client, addr = self.srv.accept()
                    self.clients[client] = ClientContext(client, addr)
                    log.info("Connexion de %s:%d", *addr)
                else:
                    self._read(sock)
        for sock in list(self.clients):
            self._drop(sock)
        self.srv.close()

    def stop(self, *_):
        """Demande l'arrêt propre (SIGTERM / Ctrl+C)."""
        self.running = False

    def _read(self, sock):
        """Lit les octets disponibles d'un client, reconstitue les trames et traite chaque message."""
        ctx = self.clients[sock]
        try:
            data = sock.recv(4096)
        except OSError:
            data = b""
        if not data:
            self._drop(sock)
            return
        try:
            messages = ctx.buf.feed(data)
        except ValueError as exc:
            log.warning("Trame invalide depuis %s : %s", ctx.addr[0], exc)
            self._drop(sock)
            return
        for msg in messages:
            try:
                self.dispatch(ctx, msg)
            except Exception:  # noqa: BLE001 — une erreur de base ne doit jamais arrêter le serveur
                log.exception("Erreur de traitement (%s)", msg.get("type") if isinstance(msg, dict) else msg)
                # Ne pas exposer au client les détails internes (SQL, chemins, configuration).
                self._send(ctx, {"type": "error", "message": "traitement impossible"})
            if sock not in self.clients:
                return

    def _drop(self, sock):
        """Ferme la connexion d'un client et clôture sa session en base."""
        ctx = self.clients.pop(sock, None)
        if ctx is None:
            return
        for key in ctx.keys:
            st = self.sessions.get(key)
            if st is None or not st.open or st.ended:
                continue
            try:   # date de fin provisoire : la session est rouverte si le poste revient
                self.db.end_session(st.id_session)
                st.open = False
            except Exception:  # noqa: BLE001
                log.warning("Fermeture de session %s impossible", st.id_session)
        self.sessions.pop(ctx.implicit, None)   # les sessions sans clé sont liées à la connexion
        log.info("Déconnexion de %s (%s)", ctx.addr[0], ctx.name)
        try:
            sock.close()
        except OSError:
            pass

    @staticmethod
    def _send(ctx, msg: dict):
        """Envoie un message JSON à un client (erreur d'envoi ignorée : le client sera retiré à la lecture suivante)."""
        try:
            ctx.sock.sendall(encode(msg))
        except OSError:
            pass

    # ------------------------------------------------------------------ traitement des messages
    def dispatch(self, ctx, msg):
        """Aiguille un message vers son traitement (batch = liste de messages)."""
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "hello":
            return self._hello(ctx, msg)
        if not ctx.authenticated:
            self._send(ctx, {"type": "error", "message": "authentification requise"})
            return self._drop(ctx.sock)
        if kind == "batch":
            return self._batch(ctx, msg)
        self._handle(ctx, msg, {}, direct=True)

    def _batch(self, ctx, msg):
        """Traite un lot dans l'ordre et acquitte le numéro du dernier message enregistré.

        Base en panne : on s'arrête sans acquitter la suite, que l'IHM renverra. Message invalide (base saine) :
        il est ignoré et acquitté, pour ne pas bloquer la file d'attente de l'IHM.
        """
        params = msg.get("sessions") if isinstance(msg.get("sessions"), dict) else {}
        dernier = None
        for sub in msg.get("messages", [])[:200]:
            if not isinstance(sub, dict):
                continue
            try:
                self._handle(ctx, sub, params)
            except Exception:  # noqa: BLE001
                if not self.db.alive():
                    log.error("Base indisponible : lot interrompu, l'IHM le renverra")
                    self._send(ctx, {"type": "error", "message": "base indisponible, enregistrement différé"})
                    break
                log.exception("Message ignoré (%s)", sub.get("type"))
            if isinstance(sub.get("n"), int):
                dernier = sub["n"]
        if dernier is not None:
            self._send(ctx, {"type": "ack", "ref": "batch", "n": dernier})

    def _handle(self, ctx, msg, params, direct=False):
        """Rattache un message à sa session, ignore un renvoi déjà enregistré, puis appelle son traitement.

        `direct` : message hors lot (ex. demande de priorité en temps réel). Si la base est indisponible, la session
        n'est pas retrouvée mais le traitement a lieu quand même : accorder la priorité ne dépend jamais de la base.
        """
        kind = msg.get("type")
        if kind in ("hello", "batch"):
            return
        handler = getattr(self, f"_on_{kind}", None)
        if handler is None:
            return self._send(ctx, {"type": "error", "message": f"type de message inconnu : {kind}"})
        n = msg.get("n") if isinstance(msg.get("n"), int) else None
        st = None
        if isinstance(msg.get("sess"), str):
            try:
                st = self._session(ctx, msg["sess"], params.get(msg["sess"]))
            except Exception:  # noqa: BLE001
                if not direct:
                    raise          # lot : interrompu sans acquittement, l'IHM le renverra
                log.warning("Session %s non rattachée (base indisponible)", msg["sess"])
                st = ctx.session = None
            if st is not None and n is not None and n <= st.last_n:
                return   # déjà enregistré (lot renvoyé après une coupure)
        handler(ctx, msg)
        st = st or ctx.session
        if st is not None and n is not None:
            st.last_n = max(st.last_n, n)

    def _etiquette(self, ctx, key):
        """Étiquette du poste enregistrée en base (colonne `client`), qui permet de retrouver la session après redémarrage."""
        return f"{ctx.name[:40]} #{key[:16]}"

    def _session(self, ctx, key, params=None):
        """Retrouve (ou recrée) la session `key` : en mémoire, sinon en base (serveur redémarré), sinon d'après ses paramètres."""
        st = self.sessions.get(key)
        if st is None:
            id_s = self.db.find_session(self._etiquette(ctx, key))
            if id_s is None and isinstance(params, dict) and self._parametres_valides(params):
                id_s = self.db.start_session(params["type_carrefour"], params["regulation"], int(params["densite"]),
                                             self._etiquette(ctx, key), heure_message({"ts": params.get("debut")}))
            if id_s is None:
                return None
            st = self._memoriser(key, SessionState(id_s))
            st.open = False   # rouverte ci-dessous
        if not st.open and not st.ended:
            self.db.reopen_session(st.id_session)
            st.open = True
        ctx.session = st
        ctx.keys.add(key)
        return st

    def _memoriser(self, key, st):
        """Garde la session en mémoire (les plus anciennes sessions terminées sont oubliées au-delà de SESSIONS_MAX)."""
        self.sessions[key] = st
        if len(self.sessions) > SESSIONS_MAX:
            for vieille in [k for k, v in self.sessions.items() if v.ended or not v.open][:100]:
                del self.sessions[vieille]
        return st

    @staticmethod
    def _parametres_valides(p):
        """Vrai si type de carrefour, régulation et densité (entier 1 à 10) sont acceptables."""
        d = p.get("densite", 5)
        return (p.get("type_carrefour") in dbm.TYPES_CARREFOUR and p.get("regulation") in dbm.REGULATIONS
                and isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= 10)

    def _hello(self, ctx, msg):
        """Authentifie le poste IHM (jeton partagé) et répond `welcome` ; un jeton invalide ferme la connexion."""
        if self.token and msg.get("token") != self.token:
            log.warning("Jeton invalide depuis %s", ctx.addr[0])
            self._send(ctx, {"type": "error", "message": "jeton invalide"})
            return self._drop(ctx.sock)
        ctx.name, ctx.authenticated = str(msg.get("client", "?"))[:60], True
        self._send(ctx, {"type": "welcome", "db": self.db.backend, "tables": list(dbm.TABLES)})

    def _on_ping(self, ctx, msg):
        """Répond `pong` (test de vie de la liaison)."""
        self._send(ctx, {"type": "pong"})

    def _on_session_start(self, ctx, msg):
        """Ouvre une session de simulation en base après validation du type de carrefour, de la régulation et de la densité."""
        if ctx.session and not msg.get("sess") and not ctx.session.ended:   # ancien protocole : une session à la fois
            self.db.end_session(ctx.id_session)
            ctx.session.ended = True
        typ, reg = msg.get("type_carrefour"), msg.get("regulation")
        if typ not in dbm.TYPES_CARREFOUR or reg not in dbm.REGULATIONS:
            return self._send(ctx, {"type": "error", "message": "type_carrefour ou regulation invalide"})
        try:
            densite = int(msg.get("densite", 5))
        except (TypeError, ValueError):
            return self._send(ctx, {"type": "error", "message": "densite doit être un entier entre 1 et 10"})
        if isinstance(msg.get("densite", 5), bool) or not 1 <= densite <= 10:
            return self._send(ctx, {"type": "error", "message": "densite doit être un entier entre 1 et 10"})
        key = msg.get("sess") if isinstance(msg.get("sess"), str) else None
        if key and key in self.sessions:          # session déjà créée (reprise) : rien à refaire
            ctx.session = self.sessions[key]
        else:
            id_s = self.db.start_session(typ, reg, densite, self._etiquette(ctx, key) if key else ctx.name, heure_message(msg))
            ctx.session = self._memoriser(key or ctx.implicit, SessionState(id_s))
            ctx.keys.add(key or ctx.implicit)
        self._send(ctx, {"type": "session_started", "id_session": ctx.id_session})

    def _on_session_end(self, ctx, msg):
        """Clôture la session de simulation en cours."""
        st = ctx.session
        if st:
            self.db.end_session(st.id_session, heure_message(msg))
            st.ended, st.open = True, False
            ctx.session = None

    def _on_vehicle(self, ctx, msg):
        """Enregistre un nouveau véhicule de la session (type validé par liste blanche)."""
        st = ctx.session
        if not st or msg.get("kind") not in dbm.TYPES_VEHICULE or msg.get("vid") in st.vehicles:
            return
        st.vehicles[msg.get("vid")] = self.db.add_vehicle(st.id_session, msg["kind"], str(msg.get("direction", "?"))[:20],
                                                          str(msg.get("destination", ""))[:20] or None)

    def _on_vehicle_state(self, ctx, msg):
        """Met à jour l'état d'un véhicule (en circulation, arrêté, a franchi le carrefour)."""
        id_v = ctx.session.vehicles.get(msg.get("vid")) if ctx.session else None
        if id_v and msg.get("etat") in dbm.ETATS_VEHICULE:
            self.db.set_vehicle_state(id_v, msg["etat"])

    def _on_priority_request(self, ctx, msg):
        """Accorde la priorité (V2I) à l'urgence, journalise la demande puis alerte les autres postes (V2V)."""
        approach, vehicle = str(msg.get("approach", "?"))[:20], str(msg.get("vehicle", "?"))
        # La décision de priorité ne dépend PAS de la base : on répond d'abord, on journalise ensuite.
        grant = {"type": "priority_grant", "approach": approach, "axis": AXIS.get(approach, "?"), "rid": msg.get("rid")}
        logged = False
        st = ctx.session
        try:
            if st and msg.get("rid") in st.priorities:
                logged = True                     # demande déjà enregistrée (renvoi)
            elif st:
                id_p = self.db.add_priority(st.id_session, st.vehicles.get(msg.get("vid")), approach, "accordée",
                                            heure_message(msg))
                st.priorities[msg.get("rid")] = id_p
                logged = True
        except Exception:  # noqa: BLE001
            log.exception("Journalisation de la demande de priorité impossible")
        grant["logged"] = logged
        self._send(ctx, grant)
        log.info("Priorité accordée à %s depuis %s", vehicle, approach)
        for other in self.clients.values():  # diffusion V2V aux autres postes
            if other is not ctx and other.authenticated:
                self._send(other, {"type": "v2v_alert", "vehicle": vehicle, "approach": approach})

    def _on_priority_log(self, ctx, msg):
        """Enregistre a posteriori une priorité : décidée par l'IHM pendant une coupure (« mode dégradé »),
        ou accordée par le serveur alors que la base était indisponible (« accordée »)."""
        st = ctx.session
        if not st or msg.get("rid") in st.priorities:
            return
        resultat = "accordée" if msg.get("resultat") == "accordée" else "mode dégradé"
        st.priorities[msg.get("rid")] = self.db.add_priority(st.id_session, st.vehicles.get(msg.get("vid")),
                                                             str(msg.get("approach", "?"))[:20], resultat,
                                                             heure_message(msg))
        if resultat == "mode dégradé":
            st.degraded.add(msg.get("rid"))

    def _on_crossing_done(self, ctx, msg):
        """Clôture la demande de priorité (durée, résultat) et journalise le passage terminé."""
        st = ctx.session
        if st:
            rid = msg.get("rid")
            id_p = st.priorities.get(rid)
            if id_p:
                self.db.finish_priority(id_p, float(msg.get("duration", 0)),
                                        "mode dégradé" if rid in st.degraded else "terminée")
            self.db.add_traffic_event(st.id_session, st.vehicles.get(msg.get("vid")), "passage terminé",
                                      f"{msg.get('vehicle', 'Véhicule')} a franchi le carrefour", heure_message(msg))
        self._send(ctx, {"type": "ack", "ref": "crossing_done"})

    def _on_traffic_event(self, ctx, msg):
        """Journalise un événement de trafic (véhicule arrêté, embouteillage détecté, passage terminé)."""
        st = ctx.session
        if st and msg.get("event") in dbm.TYPES_EVENEMENT:
            self.db.add_traffic_event(st.id_session, st.vehicles.get(msg.get("vid")), msg["event"], msg.get("details"),
                                      heure_message(msg))

    def _on_light_change(self, ctx, msg):
        """Journalise un changement d'état de feu et sa cause."""
        if ctx.session and msg.get("etat") in dbm.ETATS_FEU and msg.get("cause") in dbm.CAUSES_FEU:
            self.db.add_light_log(ctx.id_session, str(msg.get("feu", "?"))[:20], msg["etat"], msg["cause"], heure_message(msg))

    def _on_history(self, ctx, msg):
        """Renvoie les dernières lignes d'une table autorisée (liste blanche)."""
        try:
            cols, rows = self.db.history(msg.get("table", ""), msg.get("limit", 100))
        except ValueError:
            return self._send(ctx, {"type": "error", "message": "table inconnue"})
        self._send(ctx, {"type": "history_result", "table": msg.get("table"), "columns": cols, "rows": rows})

    def _on_chronology(self, ctx, msg):
        """Renvoie la chronologie de la dernière intervention de la session."""
        cols, rows = self.db.chronology(ctx.id_session)
        self._send(ctx, {"type": "history_result", "table": "chronologie", "columns": cols, "rows": rows})


def main():
    """Point d'entrée en ligne de commande."""
    ap = argparse.ArgumentParser(description="Serveur du carrefour connecté (SAÉ 3.02)")
    ap.add_argument("--host", default=os.environ.get("SERVER_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("SERVER_PORT", DEFAULT_PORT)))
    ap.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    server = IntersectionServer(args.host, args.port)
    signal.signal(signal.SIGTERM, server.stop)
    signal.signal(signal.SIGINT, server.stop)
    server.run()


if __name__ == "__main__":
    main()
