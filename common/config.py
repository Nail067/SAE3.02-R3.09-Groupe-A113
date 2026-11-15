"""Configuration partagée : deploy/carrefour.conf (+ carrefour.local.conf) et variables d'environnement.

Ordre de priorité (le dernier gagne) : valeurs par défaut < deploy/carrefour.conf < deploy/carrefour.local.conf
< variables d'environnement CARREFOUR_<NOM> (alias : CARREFOUR_HOST = IP_SERVEUR_CLIENTS).
"""
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {
    "IP_SERVEUR_CLIENTS": "192.168.56.101", "RESEAU_CLIENTS": "192.168.56.0/24",
    "IP_SERVEUR_DONNEES": "10.10.10.1", "IP_DATABASE": "10.10.10.2", "MASQUE": "24",
    "DB_NAME": "carrefour", "DB_USER": "carrefour", "DB_PASSWORD": "", "TOKEN": "",   # secrets : jamais dans le dépôt (générés par install.sh)
    "IFACE_CLIENTS": "", "IFACE_DONNEES": "",
}


def _lire(fichier: Path, cfg: dict):
    """Ajoute à `cfg` les lignes NOM=valeur d'un fichier (commentaires et lignes vides ignorés)."""
    if not fichier.is_file():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            cfg[cle.strip()] = valeur.strip().strip('"').strip("'")


def load(root: Path = ROOT) -> dict:
    """Renvoie la configuration complète sous forme de dictionnaire."""
    cfg = dict(DEFAULTS)
    for nom in ("carrefour.conf", "carrefour.local.conf"):
        _lire(Path(root) / "deploy" / nom, cfg)
    for cle in list(cfg):
        valeur = os.environ.get("CARREFOUR_" + cle, "").strip()
        if valeur:
            cfg[cle] = valeur
    hote = os.environ.get("CARREFOUR_HOST", "").strip()   # alias : adresse de la VM Serveur
    if hote:
        cfg["IP_SERVEUR_CLIENTS"] = hote
    return cfg


def dossier_donnees(racine: Path = ROOT) -> Path:
    """Dossier `donnees/` du projet ; si le projet est en lecture seule (clé USB, dossier protégé), dossier temporaire."""
    donnees = racine / "donnees"
    try:
        donnees.mkdir(exist_ok=True)
        if os.access(donnees, os.W_OK):
            return donnees
    except OSError:
        pass
    donnees = Path(tempfile.gettempdir()) / "carrefour-donnees"
    donnees.mkdir(exist_ok=True)
    return donnees
