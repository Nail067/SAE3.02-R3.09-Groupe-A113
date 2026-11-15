"""Rendu 2D du carrefour (4 voies à feux ou rond-point) avec QGraphicsScene / QGraphicsView (vue de dessus)."""
import random

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import (QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsScene,
                             QGraphicsView)

from client.simulation import CX, CY, HALF, IN_DIR, RING_ISLAND, RING_OUT, RING_STOP, SIDES, _right

NOPEN = QPen(Qt.PenStyle.NoPen)
LIGHT_COLORS = {"red": "#ff3b30", "orange": "#ffb020", "green": "#2ee36b"}


class IntersectionScene(QGraphicsScene):
    """Scène 800x800 : décor statique + synchronisation des véhicules et des feux."""

    def __init__(self):
        """Crée une scène de 800 x 800 px et les dictionnaires d'éléments graphiques (véhicules, feux)."""
        super().__init__(0, 0, 800, 800)
        self.v_items, self.lights = {}, {}

    def build(self, cfg):
        """Redessine le décor pour le type de carrefour `cfg`."""
        self.clear()
        self.v_items, self.lights = {}, {}
        rnd = random.Random(7)
        self.setBackgroundBrush(QColor("#8c9196"))
        for x, y in [(0, 0), (460, 0), (0, 460), (460, 460)]:
            self.addRect(x, y, 340, 340, NOPEN, QBrush(QColor("#9aa0a5")))
            self.addRect(x + 22, y + 22, 296, 296, NOPEN, QBrush(QColor("#3f6b44")))
            self.addRect(x + 70, y + 70, 200, 200, QPen(QColor("#1c2733"), 2), QBrush(QColor("#4b5766")))
            self.addRect(x + 90, y + 90, 160, 160, NOPEN, QBrush(QColor("#6b7889")))
            for _ in range(5):
                cx, cy, r = x + rnd.choice([40, 300]), y + rnd.randint(40, 300), rnd.randint(9, 15)
                self.addEllipse(cx - r, cy - r, 2 * r, 2 * r, NOPEN, QBrush(QColor("#2b5a31")))
        asphalt, kerb = QBrush(QColor("#3b3f45")), QBrush(QColor("#9aa0a5"))
        ring = cfg["mode"] == "round"
        if ring:  # trottoir circulaire autour de l'anneau, sous les bras de route
            self.addEllipse(CX - RING_OUT - 10, CY - RING_OUT - 10, 2 * RING_OUT + 20, 2 * RING_OUT + 20, NOPEN, kerb)
        centre = 400 if ring else 340   # les bras vont jusqu'au centre (rond-point) ou au bord du carrefour
        for rect in ((340, 0, 120, centre), (340, 800 - centre, 120, centre), (800 - centre, 340, centre, 120), (0, 340, centre, 120)):
            self.addRect(*rect, NOPEN, asphalt)
        if ring:  # chaussée circulaire, puis îlot central végétalisé bordé d'un rebord clair
            self.addEllipse(CX - RING_OUT, CY - RING_OUT, 2 * RING_OUT, 2 * RING_OUT, NOPEN, asphalt)
            self.addEllipse(CX - RING_ISLAND, CY - RING_ISLAND, 2 * RING_ISLAND, 2 * RING_ISLAND,
                            QPen(QColor("#c9ced3"), 4), QBrush(QColor("#3f6b44")))
            self.addEllipse(CX - 30, CY - 30, 60, 60, NOPEN, QBrush(QColor("#4c7d52")))
        else:
            self.addRect(340, 340, 120, 120, NOPEN, asphalt)
        dash = QPen(QColor("#e8c44a"), 2, Qt.PenStyle.CustomDashLine)
        dash.setDashPattern([6, 6])
        zebra = QPen(QColor("#f2f2f2"), 16)
        zebra.setDashPattern([0.6, 0.6])
        zebra.setCapStyle(Qt.PenCapStyle.FlatCap)
        cedez = QPen(QColor("white"), 4, Qt.PenStyle.CustomDashLine)   # ligne « cédez le passage » (pointillés)
        cedez.setDashPattern([2, 1.5])
        d_zebra, d_stop, d_ligne = (158, RING_STOP, 196) if ring else (68, 82, HALF)   # distances au centre
        for side in SIDES:
            di = IN_DIR[side]
            ri = _right(di)
            if ring:  # îlot séparateur en goutte d'eau entre la voie d'entrée et la voie de sortie
                pts = [(104, 10), (150, 7), (d_ligne, 0), (150, -7), (104, -10)]
                self.addPolygon(QPolygonF([QPointF(CX - di[0] * d + ri[0] * w, CY - di[1] * d + ri[1] * w) for d, w in pts]),
                                QPen(QColor("#c9ced3"), 2), kerb)
            far = (CX - di[0] * 400, CY - di[1] * 400)
            near = (CX - di[0] * d_ligne, CY - di[1] * d_ligne)
            self.addLine(far[0], far[1], near[0], near[1], dash)
            cw = (CX - di[0] * d_zebra, CY - di[1] * d_zebra)
            self.addLine(cw[0] - ri[0] * 60, cw[1] - ri[1] * 60, cw[0] + ri[0] * 60, cw[1] + ri[1] * 60, zebra)
            sl = (CX - di[0] * d_stop, CY - di[1] * d_stop)
            self.addLine(sl[0], sl[1], sl[0] + ri[0] * 60, sl[1] + ri[1] * 60, cedez if ring else QPen(QColor("white"), 4))
            pole = (sl[0] - di[0] * 4 + ri[0] * 70, sl[1] - di[1] * 4 + ri[1] * 70)
            if ring:
                self._add_yield(pole)
            else:
                self._add_light(side, pole)

    def _add_light(self, side, pos):
        """Dessine le boîtier d'un feu tricolore pour la branche `side` à la position `pos`."""
        box = QGraphicsRectItem(-7, -19, 14, 38)
        box.setBrush(QColor("#10151b"))
        box.setPen(QPen(QColor("#000"), 1))
        box.setPos(*pos)
        box.setZValue(20)
        self.addItem(box)
        self.lights[side] = []
        for i, y in enumerate((-11, 0, 11)):
            dot = QGraphicsEllipseItem(-4, -4, 8, 8, box)
            dot.setPos(0, y)
            dot.setPen(NOPEN)
            self.lights[side].append(dot)

    def _add_yield(self, pos):
        """Panneau « cédez le passage » (triangle pointe en bas, bord rouge)."""
        sign = QGraphicsPolygonItem(QPolygonF([QPointF(-13, -10), QPointF(13, -10), QPointF(0, 12)]))
        sign.setBrush(QColor("white"))
        sign.setPen(QPen(QColor("#c8102e"), 4))
        sign.setPos(*pos)
        sign.setZValue(20)
        self.addItem(sign)

    def _make_vehicle(self, v):
        """Crée l'élément graphique d'un véhicule (carrosserie, pare-brise, gyrophare pour l'urgence)."""
        length, width = v.length, v.width
        body = QGraphicsRectItem(-length / 2, -width / 2, length, width)
        body.setBrush(QColor(v.color))
        body.setPen(QPen(QColor(15, 15, 15, 210), 1))
        body.setZValue(10 + (5 if v.emergency else 0))
        glass = QGraphicsRectItem(length * 0.12, -width / 2 + 2, length * 0.22, width - 4, body)
        glass.setBrush(QColor(25, 35, 48, 230))
        glass.setPen(NOPEN)
        siren = None
        if v.emergency:
            siren = QGraphicsEllipseItem(-9, -9, 18, 18, body)
            siren.setPen(NOPEN)
            stripe = QGraphicsRectItem(-length / 2 + 2, -2, length - 4, 4, body)
            stripe.setBrush(QColor("#d62828") if v.color != "#d62828" else QColor("#f5f5f5"))
            stripe.setPen(NOPEN)
        self.addItem(body)
        return body, siren

    def sync(self, sim):
        """Aligne les éléments graphiques sur l'état de la simulation."""
        live = set()
        for v in sim.vehicles:
            live.add(v.id)
            if v.id not in self.v_items:
                self.v_items[v.id] = self._make_vehicle(v)
            body, siren = self.v_items[v.id]
            body.setPos(v.x, v.y)
            body.setRotation(v.angle)
            if siren is not None:
                siren.setBrush(QColor(255, 40, 40, 150) if int(sim.t * 4) % 2 else QColor(40, 130, 255, 150))
        for vid in [k for k in self.v_items if k not in live]:
            self.removeItem(self.v_items.pop(vid)[0])
        for side, dots in self.lights.items():
            state = sim.light_state(side)
            for dot, name in zip(dots, ("red", "orange", "green")):
                dot.setBrush(QColor(LIGHT_COLORS[name]) if state == name else QColor("#2a2f36"))


class SimulationView(QGraphicsView):
    """Vue qui conserve la scène entièrement visible."""

    def __init__(self, scene):
        """Vue de la scène : anticrénelage, sans cadre ni barres de défilement."""
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        """Redimensionne la vue en conservant toute la scène visible (proportions respectées)."""
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
