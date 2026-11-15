"""Client réseau V2I/V2V exécuté dans un QThread ; communique avec l'IHM uniquement par signaux Qt."""
import queue
import select
import socket

from PyQt6.QtCore import QThread, pyqtSignal

from common.protocol import FrameBuffer, encode


class NetworkClient(QThread):
    """Maintient la connexion TCP (reconnexion automatique) vers le serveur du carrefour."""

    status = pyqtSignal(bool, str)   # connecté ?, texte
    received = pyqtSignal(dict)      # message reçu du serveur
    frame = pyqtSignal(str, dict)    # ("TX"/"RX", message) pour l'onglet Réseau

    def __init__(self, host: str, port: int, token: str = ""):
        """Prépare le client (cible host:port, jeton, file d'envoi) ; la connexion est ouverte par run()."""
        super().__init__()
        self.host, self.port, self.token = host, port, token
        self._out = queue.Queue()
        self._running = True
        self._reset = False
        self.connected = False

    def configure(self, host: str, port: int, token: str = ""):
        """Change la cible ; la connexion courante est fermée puis rétablie."""
        self.host, self.port, self.token, self._reset = host, port, token, True

    def send(self, msg: dict):
        """Met un message en file d'envoi (thread-safe)."""
        self._out.put(msg)

    def stop(self):
        """Demande l'arrêt du thread."""
        self._running = False

    def run(self):
        """Boucle principale : connexion, lecture (select), envoi."""
        while self._running:
            try:
                sock = socket.create_connection((self.host, self.port), timeout=2)
            except OSError:
                self.status.emit(False, f"{self.host}:{self.port}")
                self.msleep(2000)
                continue
            self._reset = False
            # Messages restés en file d'une connexion précédente : jetés (le serveur exige le « hello » en premier ;
            # les événements à journaliser sont de toute façon conservés et renvoyés par la file locale de l'IHM).
            while not self._out.empty():
                self._out.get_nowait()
            hello = {"type": "hello", "client": "IHM-A113", "token": self.token}
            try:
                sock.sendall(encode(hello))   # toujours le premier message de la connexion
            except OSError:
                sock.close()
                self.msleep(1000)
                continue
            self.frame.emit("TX", hello)
            # Connecté seulement quand le serveur a répondu « welcome » : une connexion acceptée puis fermée aussitôt
            # (redirection de port NAT VirtualBox vers une VM dont le serveur est arrêté) compte comme un échec.
            buf = FrameBuffer()
            try:
                while self._running and not self._reset:
                    if select.select([sock], [], [], 0.05)[0]:
                        data = sock.recv(4096)
                        if not data:
                            break
                        for msg in buf.feed(data):
                            if msg.get("type") == "welcome" and not self.connected:
                                self.connected = True
                                self.status.emit(True, f"{self.host}:{self.port}")
                            self.frame.emit("RX", msg)
                            self.received.emit(msg)
                    if not self.connected:
                        continue      # rien d'autre que le « hello » avant l'authentification
                    while not self._out.empty():
                        msg = self._out.get_nowait()
                        sock.sendall(encode(msg))
                        self.frame.emit("TX", msg)
            except (OSError, ValueError):   # coupure, ou trame invalide reçue : on se reconnecte
                pass
            finally:
                sock.close()
                etait_connecte, self.connected = self.connected, False
                self.status.emit(False, f"{self.host}:{self.port}")
            if self._running and not self._reset:
                # pause avant de réessayer (pas de boucle rapide) ; plus longue si le serveur n'a jamais répondu
                self.msleep(1000 if etait_connecte else 2000)
