"""Fenêtre principale de l'IHM « Carrefour connecté » (SAÉ 3.02 – groupe A113)."""
import json
import time
import uuid
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit, QPushButton,
                             QScrollArea, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                             QWidget)

from client.network import NetworkClient
from client.outbox import Outbox
from client.scene import IntersectionScene, SimulationView
from client.simulation import EMERGENCY_TYPES, JUNCTIONS, SIDES, Simulation
from common.config import dossier_donnees

DELAI_REPONSE_MS = 2500   # sans réponse du serveur à une demande de priorité : décision locale (mode dégradé)
DELAI_ACQUIT_S = 10       # lot non acquitté après ce délai : renvoyé (le serveur ignore les doublons)

EVENT_COLORS = {"info": "#8fb3d9", "approach": "#4aa3ff", "priority": "#2ee36b", "v2v": "#c58bff",
                "crossed": "#4aa3ff", "normal": "#8fb3d9", "net": "#ffb020"}
STYLE = """
QMainWindow, QWidget#root { background:#08182b; }
QWidget { color:#dce8f5; font-size:13px; }
QTabWidget::pane { border:0; }
QTabBar::tab { background:transparent; padding:12px 18px; color:#9db4cc; font-size:14px; border-bottom:3px solid transparent; }
QTabBar::tab:selected { color:#2e9bff; border-bottom:3px solid #2e9bff; background:#10294a; }
QFrame#panel { background:#0d2240; border:1px solid #1d3b61; border-radius:6px; }
QLabel#title { font-weight:bold; font-size:15px; padding:4px 0 6px 0; }
QLabel#muted { color:#9db4cc; }
QComboBox, QLineEdit, QSpinBox { background:#0a1a30; border:1px solid #27466f; border-radius:4px; padding:6px; }
QComboBox QAbstractItemView { background:#0a1a30; selection-background-color:#1e5fa8; }
QPushButton { background:#1e7bf0; color:white; border:0; border-radius:4px; padding:10px; font-weight:bold; }
QPushButton:hover { background:#3a90ff; } QPushButton:disabled { background:#27384f; color:#7d8da3; }
QPushButton#danger { background:#17a870; } QPushButton#danger:hover { background:#1fc684; }
QPushButton#ghost { background:#16335a; }
QSlider::groove:horizontal { height:6px; background:#27466f; border-radius:3px; }
QSlider::handle:horizontal { background:#4aa3ff; width:16px; margin:-5px 0; border-radius:8px; }
QListWidget, QPlainTextEdit, QTableWidget { background:#0a1a30; border:1px solid #1d3b61; gridline-color:#1d3b61; }
QHeaderView::section { background:#12315a; border:0; padding:5px; }
QScrollBar:vertical { background:#0a1a30; width:10px; margin:0; }
QScrollBar::handle:vertical { background:#27466f; border-radius:5px; min-height:30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
"""


def panel(title=None):
    """Crée un cadre « carte » avec titre optionnel ; renvoie (cadre, layout)."""
    frame = QFrame()
    frame.setObjectName("panel")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 10, 14, 12)
    if title:
        t = QLabel(title)
        t.setObjectName("title")
        lay.addWidget(t)
    return frame, lay


def muted(text):
    """Petit libellé grisé."""
    lab = QLabel(text)
    lab.setObjectName("muted")
    return lab


class MainWindow(QMainWindow):
    """Assemble simulation, réseau (QThread) et consultation de la base de données distante."""

    def __init__(self, host, port, token=""):
        """Construit la fenêtre (onglets, simulation, client réseau) et démarre le client réseau vers host:port."""
        super().__init__()
        self.setWindowTitle("SAÉ 3.02 - Carrefour connecté")
        ecran = QGuiApplication.primaryScreen()   # taille adaptée à l'écran (portables 1366x768 compris)
        dispo = ecran.availableGeometry() if ecran else None
        self.resize(min(1440, int(dispo.width() * 0.97)) if dispo else 1440, min(900, int(dispo.height() * 0.95)) if dispo else 900)
        self.setMinimumSize(900, 520)
        self.setStyleSheet(STYLE)
        self.db_name = "MariaDB"
        self.sim = Simulation()
        self.sim.on_event, self.sim.on_request, self.sim.on_crossed = self.log_event, self.send_request, self.send_crossed
        self.scene = IntersectionScene()
        self.scene.build(self.sim.cfg)
        self.net = NetworkClient(host, port, token)
        # Journalisation sans perte : tout événement passe par une file locale (SQLite) jusqu'à son acquittement.
        self.outbox = Outbox(dossier_donnees() / "ihm_en_attente.db")
        self.sess = None                 # clé de la session de simulation en cours
        self.ready = False               # vrai après le « welcome » du serveur (authentifié)
        self.envoye = self.acquitte = 0  # dernier numéro envoyé / acquitté sur la connexion courante
        self.t_ack = time.monotonic()
        self.demande = None              # dernière demande de priorité émise
        self.ferme = False               # vrai après fermeture de la fenêtre (file locale fermée)
        self.net_up = None               # dernier état connu de la connexion (journal sans répétitions)
        self.derniere_erreur = None      # dernier message d'erreur du serveur affiché
        self.sim.on_telemetry = self.queue_telemetry
        self.net.status.connect(self.on_net_status)
        self.net.received.connect(self.on_net_message)
        self.net.frame.connect(self.on_frame)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        outer.addWidget(self._build_footer())
        self.tabs.addTab(self._build_sim_tab(), "▦  Simulation")
        self.tabs.addTab(self._build_network_tab(), "⌘  Réseau")
        self.tabs.addTab(self._build_db_tab(), "🗄  Base de données")
        self.tabs.addTab(self._build_settings_tab(host, port, token), "⚙  Paramètres")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.setCornerWidget(self._build_corner(), Qt.Corner.TopRightCorner)

        self.cb_dest.addItems(SIDES)
        self.on_sliders()
        self.last = self.last_ui = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        clock = QTimer(self)
        clock.timeout.connect(lambda: self.clock.setText(datetime.now().strftime("%H:%M:%S\n%d/%m/%Y")))
        clock.start(1000)
        self._clock_timer = clock
        self.clock.setText(datetime.now().strftime("%H:%M:%S\n%d/%m/%Y"))
        flush = QTimer(self)
        flush.timeout.connect(self.flush_telemetry)
        flush.start(400)
        self._flush_timer = flush
        self.net.start()
        self.update_status()

    # ------------------------------------------------------------------ construction
    def _build_corner(self):
        """Crée le coin supérieur droit des onglets : état de la connexion au serveur et horloge."""
        w = QWidget()
        lay = QHBoxLayout(w)
        self.srv_label = QLabel("Serveur déconnecté")
        self.clock = QLabel("")
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.clock.setMinimumHeight(44)
        lay.addWidget(self.srv_label)
        lay.addSpacing(24)
        lay.addWidget(self.clock)
        return w

    def _build_footer(self):
        """Crée le pied de page : nom du projet, binôme, voyants V2I et base de données, version."""
        f = QFrame()
        f.setStyleSheet("background:#061224; border-top:1px solid #1d3b61;")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(20, 6, 20, 6)
        lay.addWidget(QLabel("SAÉ 3.02 - Carrefour connecté   |   Groupe A113 - BENCHEKCHOU Nail-Omar & LEMASSON Ewan"), 1)
        self.foot_v2i, self.foot_db = QLabel("● V2I"), QLabel("● MariaDB")
        for lab in (self.foot_v2i, self.foot_db):
            lay.addWidget(lab)
        lay.addWidget(QLabel("v1.0.0"))
        return f

    def _build_sim_tab(self):
        """Crée l'onglet Simulation : configuration, commande d'urgence, vue du carrefour et journal des événements."""
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        # ---- colonne gauche
        left = QVBoxLayout()
        cfg, cl = panel("Configuration de la simulation")
        self.cb_junction, self.cb_vehicle, self.cb_dest = QComboBox(), QComboBox(), QComboBox()
        self.cb_junction.addItems(list(JUNCTIONS))
        self.cb_vehicle.addItems(list(EMERGENCY_TYPES))
        self.cb_junction.currentTextChanged.connect(self.on_junction_changed)
        for text, widget in (("Type de carrefour", self.cb_junction), ("Véhicule d'urgence", self.cb_vehicle),
                             ("Destination du véhicule d'urgence", self.cb_dest)):
            cl.addWidget(muted(text))
            cl.addWidget(widget)
        self.sl_density, self.lb_density = self._slider(1, 10, 6, "Densité du trafic", cl)
        self.sl_speed, self.lb_speed = self._slider(5, 20, 10, "Vitesse des véhicules", cl)
        self.sl_density.valueChanged.connect(self.on_sliders)
        self.sl_speed.valueChanged.connect(self.on_sliders)
        self.btn_start = QPushButton("Lancer la simulation")
        self.btn_start.clicked.connect(self.toggle_simulation)
        self.btn_send = QPushButton("Envoyer le véhicule d'urgence")
        self.btn_send.setObjectName("ghost")
        self.btn_send.clicked.connect(self.send_emergency_vehicle)
        cl.addWidget(self.btn_start)
        cl.addWidget(self.btn_send)
        left.addWidget(cfg)
        cmd, ml = panel("⚠  Commande d'urgence")
        ml.addWidget(QLabel("Demande de priorité V2I/V2V"))
        self.btn_priority = QPushButton("Appuyer  (Véhicule d'urgence)")
        self.btn_priority.setObjectName("danger")
        self.btn_priority.clicked.connect(self.sim.request_priority)
        ml.addWidget(self.btn_priority)
        left.addWidget(cmd)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        left.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._scrollable(lw, 320))
        # ---- centre
        self.view = SimulationView(self.scene)
        lay.addWidget(self.view, 1)
        # ---- colonne droite
        right = QVBoxLayout()
        jr, jl = panel("Journal des événements")
        self.journal = QListWidget()
        self.journal.setWordWrap(True)
        self.journal.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        jl.addWidget(self.journal)
        right.addWidget(jr, 1)
        rw = QWidget()
        rw.setLayout(right)
        right.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._scrollable(rw, 360))
        return page

    @staticmethod
    def _scrollable(widget, largeur):
        """Entoure un panneau d'une zone défilante : rien n'est coupé sur un petit écran."""
        zone = QScrollArea()
        zone.setWidget(widget)
        zone.setWidgetResizable(True)
        zone.setFrameShape(QFrame.Shape.NoFrame)
        zone.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        zone.setFixedWidth(largeur + 14)
        zone.setStyleSheet("QScrollArea { background: transparent; border: 0; } QScrollArea > QWidget > QWidget { background: transparent; }")
        return zone

    def _slider(self, lo, hi, val, caption, layout):
        """Ajoute à `layout` un curseur horizontal [lo, hi] avec son libellé ; renvoie (curseur, étiquette de valeur)."""
        row = QHBoxLayout()
        row.addWidget(muted(caption), 1)
        label = QLabel("")
        row.addWidget(label)
        layout.addLayout(row)
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)
        layout.addWidget(sl)
        return sl, label

    def _build_network_tab(self):
        """Crée l'onglet Réseau : affichage des trames JSON émises (TX) et reçues (RX)."""
        page, lay = panel("Trames V2I / V2V (TCP – JSON)")
        self.net_log = QPlainTextEdit()
        self.net_log.setReadOnly(True)
        self.net_log.setMaximumBlockCount(500)
        lay.addWidget(self.net_log)
        wrap = QWidget()
        QVBoxLayout(wrap).addWidget(page)
        return wrap

    def _build_db_tab(self):
        """Crée l'onglet Base de données : choix d'une table (ou de la chronologie) et tableau des lignes renvoyées par le serveur."""
        page, lay = panel("Historique stocké en base (via le serveur)")
        top = QHBoxLayout()
        self.cb_table = QComboBox()
        for label, name in (("★ Chronologie d'une intervention", "chronologie"), ("sessions_simulation", "sessions_simulation"), ("vehicules", "vehicules"),
                            ("evenements_priorite", "evenements_priorite"), ("evenements_trafic", "evenements_trafic"), ("journal_feux", "journal_feux")):
            self.cb_table.addItem(label, name)
        btn = QPushButton("Actualiser")
        btn.clicked.connect(self.request_history)
        top.addWidget(self.cb_table, 1)
        top.addWidget(btn)
        lay.addLayout(top)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)
        wrap = QWidget()
        QVBoxLayout(wrap).addWidget(page)
        return wrap

    def _build_settings_tab(self, host, port, token=""):
        """Crée l'onglet Paramètres : adresse, port et jeton du serveur, demande de priorité automatique."""
        page, lay = panel("Paramètres de connexion et de simulation")
        self.ed_host, self.sp_port = QLineEdit(host), QSpinBox()
        self.ed_token = QLineEdit(token)
        self.ed_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.sp_port.setRange(1024, 65535)
        self.sp_port.setValue(port)
        self.chk_auto = QCheckBox("Demande de priorité automatique à l'approche du carrefour (V2I auto)")
        self.chk_auto.toggled.connect(lambda on: setattr(self.sim, "auto_request", on))
        btn = QPushButton("Appliquer et reconnecter")
        btn.clicked.connect(lambda: self.net.configure(self.ed_host.text().strip(), self.sp_port.value(), self.ed_token.text()))
        for w in (muted("Adresse du serveur (VM Serveur)"), self.ed_host, muted("Port TCP"), self.sp_port, muted("Jeton d'authentification (facultatif)"), self.ed_token, self.chk_auto, btn):
            lay.addWidget(w)
        lay.addStretch(1)
        wrap = QWidget()
        QVBoxLayout(wrap).addWidget(page)
        return wrap

    # ------------------------------------------------------------------ simulation
    def on_junction_changed(self, name):
        """Change de carrefour (réinitialise la scène)."""
        was_running = self.sim.running
        self.sim.set_junction(name)
        self.scene.build(self.sim.cfg)
        if was_running:
            self.sim.start()
        self.update_status()

    def on_sliders(self):
        """Applique densité et vitesse."""
        self.sim.density = self.sl_density.value()
        self.sim.speed = self.sl_speed.value() / 10
        self.lb_density.setText(("Faible", "Moyenne", "Élevée")[min(2, (self.sim.density - 1) // 3)])
        self.lb_speed.setText(f"×{self.sim.speed:.1f}")

    def toggle_simulation(self):
        """Démarre ou arrête la simulation."""
        if self.sim.running:
            self.sim.stop()
            self.btn_start.setText("Lancer la simulation")
        else:
            self.sim.start()
            self.btn_start.setText("Arrêter la simulation")
        self.update_status()

    def send_emergency_vehicle(self):
        """Fait arriver le véhicule d'urgence choisi."""
        if not self.sim.running:
            self.toggle_simulation()
        self.sim.spawn_emergency(self.cb_vehicle.currentText(), self.cb_dest.currentText())

    def update_status(self):
        """Active les boutons selon l'état de la simulation et colore les témoins de connexion du pied de page."""
        em = self.sim.em
        self.btn_priority.setEnabled(bool(em and not self.sim.em_requested and not em.crossed))
        self.btn_send.setEnabled(not (em and not em.crossed))
        up = self.net.connected
        for lab in (self.foot_v2i, self.foot_db):
            lab.setStyleSheet(f"color:{'#2ee36b' if up else '#ff5a4f'};")
        attente = 0 if self.ferme else self.outbox.nombre()
        self.foot_db.setText(f"● {self.db_name}" + (f" · {attente} en attente" if attente else ""))

    def tick(self):
        """Boucle d'animation (~60 Hz) : simulation et rendu."""
        now = time.perf_counter()
        dt, self.last = min(now - self.last, 0.05), now
        if self.sim.running:
            self.sim.update(dt)
        self.scene.sync(self.sim)
        if now - self.last_ui > 0.25:
            self.last_ui = now
            self.update_status()

    # ------------------------------------------------------------------ journal
    def log_event(self, kind, text):
        """Ajoute une ligne au journal local et la renvoie au serveur pour archivage."""
        item = QListWidgetItem(f"●  {datetime.now():%H:%M:%S}   {text}")
        item.setForeground(QColor(EVENT_COLORS.get(kind, "#dce8f5")))
        self.journal.insertItem(0, item)
        while self.journal.count() > 200:
            self.journal.takeItem(self.journal.count() - 1)

    # ------------------------------------------------------------------ réseau
    def send_request(self, payload):
        """Envoie la demande V2I ; sans serveur (ou sans réponse), bascule en mode dégradé local, journalisé plus tard."""
        payload = dict(payload, ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if self.sess:
            payload["sess"] = self.sess
        self.demande = payload
        if self.net.connected and self.ready:
            self.flush_telemetry(force=True)   # les événements précédents (dont le véhicule) partent avant la demande
            self.net.send(payload)
            self.log_event("net", "Demande V2I transmise au serveur, en attente de la réponse…")
            QTimer.singleShot(DELAI_REPONSE_MS, lambda rid=payload.get("rid"): self._sans_reponse(rid))
        else:
            self._mode_degrade("Serveur injoignable : mode dégradé, décision locale (journalisée à la reconnexion)")

    def _sans_reponse(self, rid):
        """Délai écoulé sans réponse à la demande `rid` : décision locale."""
        em = self.sim.em
        if em is not None and getattr(em, "rid", None) == rid and not self.sim.granted and not em.crossed:
            self._mode_degrade("Pas de réponse du serveur : mode dégradé, décision locale (journalisée à la reconnexion)")

    def _mode_degrade(self, texte):
        """Accorde la priorité localement et met la décision en file pour le serveur (résultat « mode dégradé »)."""
        self.log_event("net", texte)
        self.sim.grant_priority()
        if self.demande:
            self.queue_telemetry(dict(self.demande, type="priority_log", resultat="mode dégradé"))

    def queue_telemetry(self, msg):
        """Écrit un événement dans la file locale (horodaté, rattaché à sa session) ; envoi groupé toutes les 0,4 s."""
        if self.ferme:
            return
        msg = dict(msg)
        msg.setdefault("ts", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if msg["type"] == "session_start":
            self.sess = uuid.uuid4().hex[:16]
            self.outbox.ajouter_session(self.sess, {"type_carrefour": msg.get("type_carrefour"), "regulation": msg.get("regulation"),
                                                    "densite": msg.get("densite"), "debut": msg["ts"]})
        if self.sess:
            msg.setdefault("sess", self.sess)
        self.outbox.ajouter(msg)
        if msg["type"] in ("session_start", "session_end"):
            if msg["type"] == "session_end":
                self.sess = None
            self.flush_telemetry()

    def flush_telemetry(self, force=False):
        """Écrit la file sur disque puis envoie le lot suivant au serveur (un lot à la fois, renvoi si non acquitté)."""
        if self.ferme:
            return
        self.outbox.valider()
        if not (self.net.connected and self.ready):
            return
        maintenant = time.monotonic()
        if self.envoye > self.acquitte:
            if maintenant - self.t_ack > DELAI_ACQUIT_S:
                self.envoye = self.acquitte          # pas d'acquittement : on renvoie à partir du dernier acquitté
            elif not force:
                return                               # un lot est en cours : on attend son acquittement
        messages, sessions = self.outbox.a_envoyer(self.envoye)
        if not messages:
            return
        if self.envoye == self.acquitte:
            self.t_ack = maintenant
        self.net.send({"type": "batch", "messages": messages, "sessions": sessions})
        self.envoye = messages[-1]["n"]

    def send_crossed(self, payload):
        """Met en file le compte rendu de passage du véhicule d'urgence (envoyé avec les autres événements)."""
        self.queue_telemetry(payload)

    def on_net_status(self, up, target):
        """Réaction aux changements d'état de la connexion (signal Qt)."""
        self.srv_label.setText(f"{'Serveur connecté' if up else 'Serveur déconnecté'}\n({target})")
        self.srv_label.setStyleSheet(f"color:{'#2ee36b' if up else '#ff5a4f'};")
        if up == self.net_up:
            return                                   # nouvelle tentative de connexion : rien de neuf à journaliser
        self.net_up = up
        self.log_event("net", f"Réseau : {'connecté à' if up else 'déconnecté de'} {target}")
        if not up:
            if self.ready and self.sim.running:
                self.log_event("net", "Les événements sont conservés sur ce poste et seront envoyés à la reconnexion")
            self.ready = False
        self.update_status()

    def on_net_message(self, msg):
        """Traite un message reçu du serveur (signal Qt, thread GUI)."""
        kind = msg.get("type")
        if kind == "welcome":
            self.db_name = msg.get("db", "?")
            self.ready = True
            self.derniere_erreur = None
            self.envoye = self.acquitte = 0          # tout ce qui n'a pas été acquitté est renvoyé
            attente = self.outbox.nombre()
            if attente:
                self.log_event("net", f"Connexion rétablie : envoi de {attente} événement(s) conservé(s) pendant la coupure")
            self.flush_telemetry()
            self.update_status()
        elif kind == "ack" and msg.get("ref") == "batch" and isinstance(msg.get("n"), int) and not self.ferme:
            self.outbox.acquitter(msg["n"])
            self.acquitte, self.t_ack = max(self.acquitte, msg["n"]), time.monotonic()
            if self.acquitte >= self.envoye:
                self.flush_telemetry()               # lot suivant tout de suite (vidage rapide après une coupure)
        elif kind == "priority_grant":
            self.sim.grant_priority()
            if msg.get("logged") is False and self.demande and msg.get("rid") == self.demande.get("rid"):
                # priorité accordée mais base indisponible : la demande est mise en file et sera journalisée plus tard
                self.queue_telemetry(dict(self.demande, type="priority_log", resultat="accordée"))
        elif kind == "error":
            texte = str(msg.get("message", "erreur"))
            if texte != self.derniere_erreur:        # pas de répétition à chaque tentative de connexion
                self.derniere_erreur = texte
                self.log_event("net", f"Serveur : {texte}")
        elif kind == "v2v_alert":
            self.log_event("v2v", f"V2V : alerte reçue ({msg.get('vehicle')} depuis {msg.get('approach')})")
        elif kind == "history_result":
            self.fill_table(msg["columns"], msg["rows"])

    def on_frame(self, direction, msg):
        """Affiche une trame dans l'onglet Réseau."""
        arrow = "→ TX" if direction == "TX" else "← RX"
        self.net_log.appendPlainText(f"{datetime.now():%H:%M:%S}  {arrow}  {json.dumps(msg, ensure_ascii=False)}")

    def on_tab_changed(self, index):
        """Charge l'historique en entrant dans l'onglet Base de données."""
        if index == 2:
            self.request_history()

    def request_history(self):
        """Demande au serveur le contenu d'une table."""
        if self.net.connected:
            if self.cb_table.currentData() == "chronologie":
                self.net.send({"type": "chronology"})
            else:
                self.net.send({"type": "history", "table": self.cb_table.currentData(), "limit": 100})

    def fill_table(self, columns, rows):
        """Remplit le tableau de l'onglet Base de données."""
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def closeEvent(self, event):
        """Clôt la session en cours (en file), conserve la file locale sur disque et arrête le thread réseau."""
        if self.sim.running:
            self.sim.stop()
        self.flush_telemetry()
        for minuterie in (self.timer, self._flush_timer, self._clock_timer):
            minuterie.stop()
        self.ferme = True
        self.outbox.fermer()
        self.net.stop()
        self.net.wait(2000)
        super().closeEvent(event)
