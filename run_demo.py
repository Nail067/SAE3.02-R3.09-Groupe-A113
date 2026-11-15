"""Démonstration en une commande : lance un serveur local (base SQLite) puis l'IHM ; arrête tout à la fermeture.

    python run_demo.py                      démonstration complète sur ce poste (aucune machine virtuelle nécessaire)
    python run_demo.py --vm IP JETON        IHM seule, connectée au serveur installé sur une VM
    python run_demo.py --vm                 idem avec la dernière adresse et le dernier jeton utilisés
                                            (mémorisés dans deploy/carrefour.local.conf, ignoré par Git)
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from common import config

ROOT = Path(__file__).resolve().parent


def port_libre(prefere: int = 5050) -> int:
    """Renvoie le port TCP préféré s'il est libre sur 127.0.0.1, sinon le premier port libre suivant."""
    for port in [prefere, *range(prefere + 1, prefere + 50)]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("aucun port libre trouvé")


def attendre(port: int, delai: float = 15.0) -> bool:
    """Attend que le serveur accepte les connexions ; renvoie False si le délai est dépassé."""
    fin = time.time() + delai
    while time.time() < fin:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def dossier_donnees() -> Path:
    """Dossier `donnees/` du projet ; si le projet est en lecture seule (clé USB, dossier protégé), dossier temporaire."""
    return config.dossier_donnees(ROOT)


def memoriser(hote: str = "", jeton: str = "", fichier: Path = ROOT / "deploy" / "carrefour.local.conf") -> None:
    """Enregistre l'adresse du serveur et le jeton dans carrefour.local.conf (non versionné) pour les lancements suivants.

    Les autres lignes du fichier sont conservées ; un dossier en lecture seule est ignoré sans erreur.
    """
    nouvelles = {"IP_SERVEUR_CLIENTS": hote, "TOKEN": jeton}
    nouvelles = {k: v for k, v in nouvelles.items() if v}
    if not nouvelles:
        return
    try:
        lignes = fichier.read_text(encoding="utf-8").splitlines() if fichier.is_file() else []
        lignes = [ligne for ligne in lignes if ligne.split("=", 1)[0].strip() not in nouvelles]
        lignes += [f"{k}={v}" for k, v in nouvelles.items()]
        fichier.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    """Point d'entrée : démonstration locale (par défaut) ou IHM seule vers les VM (--vm)."""
    ap = argparse.ArgumentParser(description="Démarrage rapide du carrefour connecté")
    ap.add_argument("--vm", action="store_true", help="se connecter aux VM au lieu du serveur local de démonstration")
    ap.add_argument("hote", nargs="?", default="", help="avec --vm : adresse IP de la VM serveur")
    ap.add_argument("jeton", nargs="?", default="", help="avec --vm : jeton affiché à la fin de install.sh")
    args = ap.parse_args()
    if args.vm:
        hote, jeton = args.hote.strip(), args.jeton.strip()
        memoriser(hote, jeton)
        cmd = [sys.executable, "-m", "client.main"] + (["--host", hote] if hote else []) + (["--token", jeton] if jeton else [])
        return subprocess.call(cmd, cwd=ROOT)

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # fermeture propre (finally ci-dessous)
    donnees = dossier_donnees()
    port = port_libre()
    env = dict(os.environ, SQLITE_PATH=str(donnees / "demo.db"), PYTHONUNBUFFERED="1")
    for cle in ("DB_HOST", "CARREFOUR_TOKEN"):
        env.pop(cle, None)
    with open(donnees / "serveur.log", "w", encoding="utf-8") as journal:
        serveur = subprocess.Popen([sys.executable, "-m", "server.server", "--host", "127.0.0.1", "--port", str(port)],
                                   cwd=ROOT, env=env, stdout=journal, stderr=subprocess.STDOUT)
        try:
            if not attendre(port):
                print("Le serveur de démonstration n'a pas démarré : voir donnees/serveur.log", file=sys.stderr)
                return 1
            print(f"Serveur de démonstration prêt (127.0.0.1:{port}). Ouverture de l'interface...")
            return subprocess.call([sys.executable, "-m", "client.main", "--host", "127.0.0.1", "--port", str(port)],
                                   cwd=ROOT, env=env)
        except KeyboardInterrupt:
            return 0
        finally:
            serveur.terminate()
            try:
                serveur.wait(5)
            except subprocess.TimeoutExpired:
                serveur.kill()


if __name__ == "__main__":
    sys.exit(main())
