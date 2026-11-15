"""Moteur de simulation du carrefour connecté (logique pure, sans dépendance Qt).

Circulation à droite, deux types de carrefour (4 voies à feux, rond-point), véhicules d'urgence
et prise en charge des demandes de priorité V2I/V2V.
"""
import math
import random

CX = CY = 400                 # centre de la scène (800 x 800)
EDGE, HALF, LANE = 400, 60, 30
S_STOP = EDGE - 82            # abscisse curviligne de la ligne d'arrêt (feux)
ACC, DECEL = 90.0, 200.0      # accélération / décélération (px/s²)
SIDES = ("Nord", "Sud", "Est", "Ouest")
IN_DIR = {"Nord": (0, 1), "Sud": (0, -1), "Est": (-1, 0), "Ouest": (1, 0)}    # sens en entrant depuis ce côté
OUT_DIR = {"Nord": (0, -1), "Sud": (0, 1), "Est": (1, 0), "Ouest": (-1, 0)}   # sens en sortant vers ce côté
OPP = {"Nord": "Sud", "Sud": "Nord", "Est": "Ouest", "Ouest": "Est"}
RIGHT_OF = {"Nord": "Ouest", "Ouest": "Sud", "Sud": "Est", "Est": "Nord"}     # côté à droite (virage à droite)
# Rond-point, distances au centre (px) : îlot central, axe de la voie circulante, bord extérieur de l'anneau,
# début de la zone de croisement, ligne de cédez-le-passage ; angle d'insertion / de sortie (degrés)
RING_ISLAND, RING_R, RING_OUT, RING_HALF, RING_STOP = 58, 79, 100, 108, 118
RING_JOIN = 24

JUNCTIONS = {
    "Carrefour à 4 voies": dict(mode="lights", phases=[{"Nord", "Sud"}, {"Est", "Ouest"}]),
    "Rond-point": dict(mode="round", phases=[]),
}
DB_MAP = {  # (type_carrefour, regulation) tels que stockés en base
    "Carrefour à 4 voies": ("4 branches", "feux"), "Rond-point": ("rond-point", "giratoire")}
KIND_FR = {"car": "voiture", "truck": "camion", "bus": "bus"}
EMERGENCY_TYPES = {"Ambulance": "#f4f6f8", "Pompiers": "#d62828", "Police": "#2b4c9b"}
CAR_COLORS = ["#d93a2f", "#2f6fd9", "#e8e8e8", "#202225", "#f0b429", "#2fa36b", "#e0782c", "#7a8590", "#8a4fd0"]


def _right(d):
    """Renvoie le vecteur directeur tourné d'un quart de tour vers la droite (circulation à droite)."""
    return (-d[1], d[0])


def _dot(a, b):
    """Produit scalaire de deux vecteurs 2D."""
    return a[0] * b[0] + a[1] * b[1]


class Path:
    """Trajectoire polygonale paramétrée par l'abscisse curviligne s."""

    def __init__(self, pts):
        """Construit la trajectoire à partir de ses points et précalcule les abscisses curvilignes cumulées."""
        self.pts, self.cum = pts, [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))
        self.length = self.cum[-1]
        self.s_exit = self.cum[-2]  # fin de la zone de croisement
        self._box = None

    def box_points(self):
        """Points échantillonnés de la trajectoire dans la zone de croisement."""
        if self._box is None:
            self._box = [self.pose(s)[:2] for s in range(int(self.cum[1]), int(self.s_exit) + 1, 10)]
        return self._box

    def pose(self, s):
        """Renvoie (x, y, angle_radians) à l'abscisse s."""
        s = min(max(s, 0.0), self.length - 1e-6)
        i = 1
        while self.cum[i] < s:
            i += 1
        a, b = self.pts[i - 1], self.pts[i]
        seg = self.cum[i] - self.cum[i - 1]
        t = (s - self.cum[i - 1]) / seg if seg else 0.0
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, math.atan2(b[1] - a[1], b[0] - a[0])


def build_path(origin, dest, lane_off=LANE):
    """Construit la trajectoire (tout droit, droite ou gauche) d'un côté d'entrée vers un côté de sortie."""
    di, do = IN_DIR[origin], OUT_DIR[dest]
    ri, ro = _right(di), _right(do)
    p0 = (CX - di[0] * EDGE + ri[0] * lane_off, CY - di[1] * EDGE + ri[1] * lane_off)
    e = (CX - di[0] * HALF + ri[0] * lane_off, CY - di[1] * HALF + ri[1] * lane_off)
    x = (CX + do[0] * HALF + ro[0] * LANE, CY + do[1] * HALF + ro[1] * LANE)
    q = (CX + do[0] * EDGE + ro[0] * LANE, CY + do[1] * EDGE + ro[1] * LANE)
    pts = [p0, e]
    if di != do:  # virage : courbe de Bézier quadratique
        k = _dot((x[0] - e[0], x[1] - e[1]), di)
        c = (e[0] + di[0] * k, e[1] + di[1] * k)
        for i in range(1, 12):
            t = i / 12
            pts.append(((1 - t) ** 2 * e[0] + 2 * (1 - t) * t * c[0] + t * t * x[0],
                        (1 - t) ** 2 * e[1] + 2 * (1 - t) * t * c[1] + t * t * x[1]))
    return Path(pts + [x, q])


def _lisser(pts, passes=2):
    """Lissage de Chaikin : arrondit les angles de la polyligne en gardant ses deux extrémités."""
    for _ in range(passes):
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out += [(0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]),
                    (0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1])]
        pts = out + [pts[-1]]
    return pts


def build_ring_path(origin, dest, lane_off=LANE):
    """Trajectoire de rond-point : entrée, arc de cercle dans le sens anti-horaire (vu de dessus), sortie."""
    di, do = IN_DIR[origin], OUT_DIR[dest]
    ri, ro = _right(di), _right(do)
    p0 = (CX - di[0] * EDGE + ri[0] * lane_off, CY - di[1] * EDGE + ri[1] * lane_off)
    e = (CX - di[0] * RING_HALF + ri[0] * lane_off, CY - di[1] * RING_HALF + ri[1] * lane_off)
    x = (CX + do[0] * RING_HALF + ro[0] * LANE, CY + do[1] * RING_HALF + ro[1] * LANE)
    q = (CX + do[0] * EDGE + ro[0] * LANE, CY + do[1] * EDGE + ro[1] * LANE)
    join = math.radians(RING_JOIN)
    a_in = math.atan2(-di[1], -di[0]) - join * lane_off / LANE
    a_out = math.atan2(do[1], do[0]) + join
    arc = (a_in - a_out) % (2 * math.pi)          # les angles décroissent : sens de circulation (écran, y vers le bas)
    n = max(2, round(arc / math.radians(10)))
    ring = [(CX + RING_R * math.cos(a_in - arc * k / n), CY + RING_R * math.sin(a_in - arc * k / n)) for k in range(n + 1)]
    return Path([p0] + _lisser([e] + ring + [x]) + [q])


class LightController:
    """Cycle de feux (vert 8 s, orange 2 s, tout-rouge 1 s) avec préemption pour véhicule d'urgence."""

    def __init__(self, phases):
        """Initialise le cycle sur la première phase (liste d'ensembles de branches vertes simultanément)."""
        self.phases, self.idx, self.t, self.stage = [set(ph) for ph in phases], 0, 0.0, "green"
        self.hold, self.target, self.base = False, 0, len(self.phases)

    def request(self, approach):
        """Ajoute une phase réservée à la seule voie `approach` et la force jusqu'à `release()`."""
        self.phases.append({approach})
        self.target, self.hold = len(self.phases) - 1, True

    def release(self):
        """Supprime la phase d'urgence et reprend le cycle normal."""
        self.hold, self.t = False, 5.0
        if len(self.phases) > self.base:
            tmp = self.phases.pop()
            if self.idx >= len(self.phases):
                self.idx = next(i for i, ph in enumerate(self.phases) if tmp <= ph)
            self.target = min(self.target, len(self.phases) - 1)

    def update(self, dt):
        """Fait avancer le cycle de feux."""
        self.t += dt
        if self.stage == "green":
            if self.hold and self.idx == self.target:
                self.t = 0.0
            elif self.t >= (0.0 if self.hold else 8.0):
                self.stage, self.t = "orange", 0.0
        elif self.stage == "orange" and self.t >= 2.0:
            self.stage, self.t = "allred", 0.0
        elif self.stage == "allred" and self.t >= 1.0:
            self.idx = self.target if self.hold else (self.idx + 1) % len(self.phases)
            self.stage, self.t = "green", 0.0

    def state(self, approach):
        """État du feu ('green', 'orange' ou 'red') pour une branche."""
        if approach in self.phases[self.idx] and self.stage in ("green", "orange"):
            return self.stage
        return "red"


_CONFLICTS = {}


def paths_conflict(a, b):
    """Vrai si les trajectoires de deux véhicules se croisent ou fusionnent dans le carrefour."""
    same = a.origin == b.origin
    if same and not (a.emergency or b.emergency):
        return False  # même branche : géré par le suivi de véhicule
    k = (a.key, b.key)
    if k not in _CONFLICTS:  # seuil plus serré pour l'urgence qui double dans sa propre file
        _CONFLICTS[k] = any(math.dist(p, q) < (19 if same else 26)
                            for p in a.path.box_points() for q in b.path.box_points())
    return _CONFLICTS[k]


_POINTS_COMMUNS = {}
MARGE = 0.7   # rond-point : marge de sécurité (s) avant et après le passage d'un autre véhicule
V_PRUDENCE = 55   # vitesse (px/s) d'un véhicule d'urgence qui s'engage sur un signal fermé, sans priorité V2I


def _points_communs(a, b):
    """Couples (s_a, s_b) : abscisses sur chaque trajectoire des endroits où elles se croisent ou se confondent."""
    k = (a.key, b.key)
    if k not in _POINTS_COMMUNS:
        seuil, pts_b, debut = 19 if a.origin == b.origin else 26, b.path.box_points(), int(a.path.cum[1])
        couples = []
        for i, p in enumerate(a.path.box_points()):
            d, j = min((math.dist(p, q), j) for j, q in enumerate(pts_b))
            if d < seuil:
                couples.append((debut + 10 * i, int(b.path.cum[1]) + 10 * j))
        _POINTS_COMMUNS[k] = couples
    return _POINTS_COMMUNS[k]


def menace(o, v, marge=MARGE):
    """Rond-point : `o` empêche-t-il `v` de s'insérer ? (acceptation d'intervalle)

    Pour chaque endroit commun aux deux trajectoires que `o` n'a pas encore dépassé, on estime l'intervalle de temps
    pendant lequel `o` puis `v` l'occupent (`v` en accélérant depuis sa vitesse actuelle). `v` cède seulement si ces
    intervalles, élargis de MARGE, se chevauchent. Un véhicule déjà passé devant n'est jamais attendu : `v` le suit
    à distance de sécurité, sans attendre la fin de son trajet.
    """
    if not paths_conflict(o, v):
        return False
    vo = max(o.v, 50.0)
    for s_o, s_v in _points_communs(o, v):
        arriere_o = o.s - o.length / 2
        if arriere_o >= s_o:
            continue                                                    # `o` est déjà passé à cet endroit
        o_debut, o_fin = max(0.0, s_o - (o.s + o.length / 2)) / vo, (s_o - arriere_o) / vo
        d = max(0.0, s_v - (v.s + v.length / 2))
        v_debut = (-v.v + math.sqrt(v.v ** 2 + 2 * ACC * d)) / ACC
        v_fin = v_debut + v.length / max(v.v + ACC * v_debut, 40.0)
        if o_debut - marge < v_fin and v_debut - marge < o_fin:
            return True
    return False


class Vehicle:
    """Véhicule suivant une trajectoire, avec modèle de suivi simple."""
    _next_id = 0
    SPECS = {"car": (30, 16, 85), "truck": (46, 18, 70), "bus": (52, 18, 70), "emergency": (34, 16, 140)}

    def __init__(self, kind, origin, dest, color, lane_off=LANE, ring=False):
        """Crée un véhicule (type, branche d'origine, destination, couleur) et calcule sa trajectoire."""
        Vehicle._next_id += 1
        self.id, self.kind, self.origin, self.dest, self.color = Vehicle._next_id, kind, origin, dest, color
        self.length, self.width, self.vmax = self.SPECS[kind][0], self.SPECS[kind][1], self.SPECS[kind][2]
        self.emergency = kind == "emergency"
        self.path = (build_ring_path if ring else build_path)(origin, dest, lane_off)
        self.s, self.v = 0.0, 40.0
        self.wait = self.blocked = 0.0
        self.entered = self.done = self.crossed = self.claimed = False
        self.etat = "en circulation"  # état tel que stocké en base
        self.key = (origin, dest, lane_off, ring)
        self.x = self.y = self.angle = self.hx = self.hy = 0.0
        self.refresh_pose()

    def refresh_pose(self):
        """Met à jour position et cap depuis l'abscisse curviligne."""
        self.x, self.y, a = self.path.pose(self.s)
        self.hx, self.hy, self.angle = math.cos(a), math.sin(a), math.degrees(a)


class Simulation:
    """Simulation complète : trafic, régulation, urgence."""

    def __init__(self):
        """Initialise la simulation (callbacks vides, densité, vitesse) sur le premier type de carrefour."""
        self.on_event = lambda kind, text: None
        self.on_request = lambda payload: None
        self.on_crossed = lambda payload: None
        self.on_telemetry = lambda msg: None   # messages destinés au serveur (session, véhicules, feux, événements)
        self.telemetry, self._rid = False, 0
        self.density, self.speed, self.auto_request = 6, 1.0, False
        self.running = False
        self.set_junction(next(iter(JUNCTIONS)))

    # ---------------------------------------------------------------- configuration
    def set_junction(self, name):
        """Change de type de carrefour et remet la simulation à zéro."""
        self.junction, self.cfg = name, JUNCTIONS[name]
        self.ctrl = LightController(self.cfg["phases"]) if self.cfg["mode"] == "lights" else None
        self.vehicles, self.em, self.t = [], None, 0.0
        self.em_requested = self.granted = False
        self.interventions = 0
        self.last_light, self.jam, self.last_stop, self.last_jam, self.return_until = {}, {}, {}, 0.0, 0.0

    def start(self):
        """Démarre la simulation avec un préchauffage pour obtenir directement du trafic dense."""
        self.set_junction(self.junction)
        self.running = True
        for _ in range(120):
            self.update(0.1, warmup=True)
        typ, reg = DB_MAP[self.junction]
        self.telemetry = True
        self.on_telemetry({"type": "session_start", "type_carrefour": typ, "regulation": reg, "densite": self.density})
        self.on_event("info", "Simulation démarrée")

    def stop(self):
        """Arrête la simulation."""
        if self.telemetry:
            self.on_telemetry({"type": "session_end"})
        self.running, self.telemetry = False, False

    # ---------------------------------------------------------------- urgence
    @property
    def emergency_active(self):
        """Vrai tant qu'un véhicule d'urgence bénéficie de la priorité V2I (accordée par le serveur)."""
        return self.em is not None and self.granted and not self.em.crossed

    @property
    def em_present(self):
        """Vrai tant qu'un véhicule d'urgence est en approche ou dans le carrefour, bouton pressé ou non."""
        return self.em is not None and not self.em.crossed

    def spawn_emergency(self, label, dest):
        """Fait apparaître un véhicule d'urgence vers `dest`, depuis une branche au hasard."""
        if self.em is not None and not self.em.crossed:
            return False
        if dest not in SIDES:
            return False
        origin = random.choice([s for s in SIDES if s != dest])
        self.em = Vehicle("emergency", origin, dest, EMERGENCY_TYPES.get(label, "#fff"), lane_off=0, ring=self._ring)
        self.em.label = label
        self.em_requested = self.granted = False
        self.vehicles.append(self.em)
        self._tele_vehicle(self.em)
        self.on_event("approach", f"Véhicule d'urgence en approche ({origin})")
        self.on_event("v2v", "V2V : les véhicules détectent l'urgence et lui cèdent le passage")
        return True

    def request_priority(self):
        """Émet la demande V2I (via le callback `on_request`)."""
        if self.em is None or self.em_requested or self.em.crossed:
            return False
        self.em_requested, self.t_request = True, self.t
        self._rid += 1
        self.em.rid = self._rid
        self.on_event("priority", f"Demande de priorité émise ({self.em.label})")
        self.on_request({"type": "priority_request", "vehicle": self.em.label, "approach": self.em.origin,
                         "destination": self.em.dest, "junction": self.junction, "vid": self.em.id, "rid": self._rid})
        return True

    def grant_priority(self):
        """Applique l'ordre de priorité (reçu du serveur ou décidé localement en mode dégradé)."""
        if self.em is None or self.granted or self.em.crossed or not self.em_requested:
            return
        self.granted = True
        if self.ctrl:
            self.ctrl.request(self.em.origin)
            self.on_event("priority", f"Feu vert uniquement pour la voie {self.em.origin}")
        else:
            self.on_event("priority", "Priorité accordée : les autres branches marquent l'arrêt")
        self.on_event("v2v", f"V2V : file {self.em.origin} avertie, couloir central dégagé")

    # ---------------------------------------------------------------- accesseurs
    def light_state(self, side):
        """État du feu d'une branche (None hors régulation par feux)."""
        return self.ctrl.state(side) if self.ctrl else None

    @property
    def _ring(self):
        """Vrai si le carrefour courant est un rond-point."""
        return self.cfg["mode"] == "round"

    @property
    def s_stop(self):
        """Abscisse curviligne de la ligne d'arrêt (feux) ou de cédez-le-passage (rond-point)."""
        return EDGE - RING_STOP if self._ring else S_STOP

    # ---------------------------------------------------------------- télémétrie vers le serveur
    def _tele_vehicle(self, v):
        """Signale au serveur l'apparition d'un véhicule (si la télémétrie est active)."""
        if self.telemetry:
            kind = v.label.lower() if v.emergency else KIND_FR[v.kind]
            self.on_telemetry({"type": "vehicle", "vid": v.id, "kind": kind, "direction": v.origin, "destination": v.dest})

    def _tele_state(self, v):
        """Signale les changements d'état d'un véhicule (arrêté, a franchi le carrefour)."""
        if v.etat == "a franchi le carrefour":
            return
        if v.s - v.length / 2 >= v.path.s_exit:
            etat = "a franchi le carrefour"
        elif v.wait > 6 and v.v < 3:
            etat = "arrêté"
        else:
            return
        if etat == v.etat:
            return
        v.etat = etat
        self.on_telemetry({"type": "vehicle_state", "vid": v.id, "etat": etat})
        if etat == "arrêté" and self.t - self.last_stop.get(v.origin, -99) > 10:
            self.last_stop[v.origin] = self.t
            name = v.label.lower() if v.emergency else KIND_FR[v.kind]
            self.on_telemetry({"type": "traffic_event", "vid": v.id, "event": "véhicule arrêté",
                               "details": f"{name} immobilisé, branche {v.origin}"})

    def _tele_lights(self):
        """Journal des feux : un message à chaque changement d'état, avec sa cause."""
        if self.ctrl is None:      # carrefours STOP / priorité à droite : pas de feux à journaliser
            return
        for side in SIDES:
            state = self.ctrl.state(side)
            if self.last_light.get(side) != state:
                self.last_light[side] = state
                cause = ("priorité urgence" if self.granted else
                         "retour au cycle normal" if self.t < self.return_until else "cycle normal")
                self.on_telemetry({"type": "light_change", "feu": side, "etat": {"green": "vert", "orange": "orange", "red": "rouge"}[state],
                                   "cause": cause})

    def _tele_jam(self):
        """Détection d'embouteillage : au moins 6 véhicules à l'arrêt sur une branche."""
        if self.t - self.last_jam < 2.0:
            return
        self.last_jam = self.t
        for side in SIDES:
            n = sum(1 for v in self.vehicles if v.origin == side and not v.entered and v.v < 3)
            if n >= 6 and not self.jam.get(side):
                self.jam[side] = True
                self.on_telemetry({"type": "traffic_event", "event": "embouteillage détecté",
                                   "details": f"{n} véhicules à l'arrêt, branche {side}"})
            elif n < 3:
                self.jam[side] = False

    # ---------------------------------------------------------------- boucle
    def update(self, dt, warmup=False):
        """Avance la simulation de `dt` secondes."""
        self.t += dt
        if self.ctrl:
            self.ctrl.update(dt)
        if self.telemetry:
            self._tele_lights()
            self._tele_jam()
        self._spawn(dt)
        if (self.auto_request and self.em and not self.em_requested and not warmup
                and self.s_stop - (self.em.s + self.em.length / 2) < 220):
            self.request_priority()
        for v in self.vehicles:
            self._step(v, dt)
        if self.em and not self.em.crossed and self.em.s - self.em.length / 2 >= self.em.path.s_exit:
            self._emergency_crossed()
        self.vehicles = [v for v in self.vehicles if not v.done]
        if self.em and self.em.done:
            self.em = None

    def _emergency_crossed(self):
        """Traite le franchissement par le véhicule d'urgence : fin de priorité, retour au cycle normal, compte rendu au serveur."""
        em = self.em
        em.crossed = True
        was_granted, self.granted = self.granted, False
        self.return_until = self.t + 6.0
        if self.ctrl:
            self.ctrl.release()
        if was_granted:
            self.interventions += 1
            self.on_event("crossed", f"{em.label} a franchi le carrefour")
            self.on_event("normal", "Retour au cycle normal du carrefour")
            self.on_crossed({"type": "crossing_done", "vehicle": em.label, "approach": em.origin,
                             "destination": em.dest, "junction": self.junction,
                             "duration": round(self.t - self.t_request, 1), "vid": em.id, "rid": getattr(em, "rid", None)})
        else:
            self.on_event("crossed", f"{em.label} a franchi le carrefour (passage cédé par les véhicules, sans demande V2I)")

    def _spawn(self, dt):
        """Fait apparaître de nouveaux véhicules sur chaque branche selon la densité de trafic."""
        rate = 0.12 + 0.09 * self.density  # véhicules / s / branche
        for side in SIDES:
            if random.random() > rate * dt:
                continue
            if any(o.origin == side and not o.emergency and o.s < 85 for o in self.vehicles):
                continue
            r = random.random()
            dest = OPP[side] if r < 0.7 else (RIGHT_OF[side] if r < 0.92 else OPP[RIGHT_OF[side]])
            k = random.random()
            kind, color = (("bus", "#f0b429") if k < 0.06 else ("truck", random.choice(["#e8e8e8", "#8a949e"]))
                           if k < 0.14 else ("car", random.choice(CAR_COLORS)))
            veh = Vehicle(kind, side, dest, color, ring=self._ring)
            self.vehicles.append(veh)
            self._tele_vehicle(veh)

    def _leader_gap(self, v):
        """Distance libre jusqu'au véhicule qui précède `v` sur sa trajectoire (None si aucun)."""
        if v.blocked > 3:  # anti-interblocage
            return None
        best = None
        for o in self.vehicles:
            if o is v or o.done:
                continue
            dx, dy = o.x - v.x, o.y - v.y
            f = dx * v.hx + dy * v.hy
            if f <= 0 or f > 140 or abs(dx * v.hy - dy * v.hx) > 16:
                continue
            gap = f - (v.length + o.length) / 2
            best = gap if best is None else min(best, gap)
        return best

    def _in_box(self, o):
        """Vrai si le véhicule `o` se trouve dans la zone de croisement du carrefour."""
        demi = RING_HALF if self._ring else HALF
        return abs(o.x - CX) < demi and abs(o.y - CY) < demi

    def _free_to_claim(self, v):
        """Réservation du carrefour : aucun véhicule engagé ne doit croiser mon trajet et la sortie doit être libre."""
        ex, ey, _ = v.path.pose(v.path.s_exit + v.length + 10)
        for o in self.vehicles:
            if o is v or o.done:
                continue
            if (self.em_present and not v.emergency and o is self.em
                    and self.em.s + self.em.length / 2 > self.s_stop - 300 and paths_conflict(v, self.em)):
                return False  # les véhicules ont repéré l'urgence : le carrefour lui est laissé libre
            if self._ring:
                if (o.claimed or o.entered) and menace(o, v, 0.2 if v.emergency else MARGE):
                    return False
            elif o.claimed and paths_conflict(v, o):
                return False
            if math.hypot(o.x - ex, o.y - ey) < 28 and o.v < 8:
                return False
        return True

    def _may_enter(self, v, d):
        """Décide si `v` peut franchir la ligne d'arrêt (d = distance restante)."""
        if v.emergency:   # l'urgence s'engage dès que la voie est libre (`_free_to_claim`), même au feu rouge
            return True
        if self.cfg["mode"] == "lights":
            st = self.ctrl.state(v.origin)
            return st == "green" or (st == "orange" and v.v ** 2 / (2 * DECEL) > d)
        # rond-point : on cède le passage (la réservation `_free_to_claim` s'en charge) ; avec la priorité V2I, les autres branches marquent l'arrêt
        return not (self.emergency_active and v.origin != self.em.origin)

    def _step(self, v, dt):
        """Avance le véhicule `v` de `dt` secondes : suivi du véhicule de tête, arrêt au feu ou au cédez-le-passage, franchissement."""
        limit = v.vmax * self.speed
        gap = self._leader_gap(v)
        if gap is not None:
            limit = min(limit, math.sqrt(2 * DECEL * max(gap - 10, 0)))
        front = v.s + v.length / 2
        if not v.entered:
            if front > self.s_stop:
                v.entered = v.claimed = True    # engagé (même sans réservation préalable) : les autres le voient
            else:
                d = self.s_stop - front
                if v.emergency and not self.granted and self.ctrl and self.ctrl.state(v.origin) != "green" and d < 140:
                    limit = min(limit, V_PRUDENCE)   # signal fermé et pas de priorité V2I : l'urgence s'engage prudemment
                if not (v.claimed or (self._may_enter(v, d) and self._free_to_claim(v))):
                    limit = min(limit, math.sqrt(2 * DECEL * max(d - 2, 0)))
                elif d < 30 + v.v ** 2 / (2 * DECEL):
                    v.claimed = True  # engagement : le véhicule réserve le carrefour
        v.v = min(limit, v.v + ACC * dt) if limit > v.v else max(limit, v.v - DECEL * 1.6 * dt)
        if v.v < 3:
            v.wait += dt
        v.blocked = v.blocked + dt if (self._in_box(v) and v.v < 2) else 0.0
        v.s += v.v * dt
        if self.telemetry:
            self._tele_state(v)
        if v.claimed and v.s - v.length / 2 >= v.path.s_exit:
            v.claimed = False  # carrefour libéré
        if v.s >= v.path.length - 1:
            v.done = True
        else:
            v.refresh_pose()
