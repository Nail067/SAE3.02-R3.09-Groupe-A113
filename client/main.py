"""Point d'entrée de l'IHM :  python -m client.main [--host 192.168.56.101] [--port 5050]"""
import argparse
import sys

from PyQt6.QtWidgets import QApplication

from client.main_window import MainWindow
from common.config import load
from common.protocol import DEFAULT_PORT


CFG = load()


def main():
    """Analyse les arguments puis lance l'application Qt."""
    ap = argparse.ArgumentParser(description="SAÉ 3.02 – IHM du carrefour connecté")
    ap.add_argument("--host", default=CFG["IP_SERVEUR_CLIENTS"], help="adresse IP du serveur (défaut : deploy/carrefour.conf)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--token", default=CFG["TOKEN"], help="jeton partagé avec le serveur (si activé)")
    args = ap.parse_args()
    app = QApplication(sys.argv)
    win = MainWindow(args.host, args.port, args.token)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
