# SAÉ 3.02 – Carrefour connecté (V2I / V2V)

**Groupe A113** – BENCHEKCHOU Nail-Omar & LEMASSON Ewan
Dépôt : `https://github.com/Nail067/SAE3.02-R3.09-Groupe-A113`

Maquette d'un carrefour connecté : un véhicule d'urgence (ambulance, pompiers, police) arrive dans un bouchon et
envoie une demande de priorité (V2I). Le serveur l'enregistre en base, ordonne le passage au vert de **sa voie seule**
(ou l'arrêt des autres branches au rond-point), puis le carrefour reprend son cycle normal une fois le véhicule passé.

## Démarrage rapide : que faire selon ce dont on dispose

| On dispose de… | Base + serveur | Interface (IHM) |
|---|---|---|
| **Un PC seul** (aucune VM) | lancés automatiquement sur le PC | `demarrer.bat` (Windows) / `bash demarrer.sh` → [section A](#a-sans-machine-virtuelle-un-pc-suffit) |
| **1 VM Linux** | `sudo ./install.sh tout` | sur le PC : `demarrer.bat vm <IP> <JETON>` → [section B](#b-sur-des-vm-quelconques-1-2-3-vm-ou-plus) |
| **2 VM Linux** | VM 1 : base · VM 2 : serveur | sur le PC → [section B](#b-sur-des-vm-quelconques-1-2-3-vm-ou-plus) |
| **3 VM ou plus** | VM 1 : base · VM 2 : serveur | VM 3 si elle a un bureau graphique, sinon le PC → [section B](#b-sur-des-vm-quelconques-1-2-3-vm-ou-plus) |
| Le réseau VirtualBox segmenté de l'équipe | voir [`deploy/FICHE_PROCEDURALE.md`](deploy/FICHE_PROCEDURALE.md) | |

**Aucun mot de passe ni jeton n'est stocké dans ce dépôt** : `install.sh` les génère sur la VM et les affiche à la fin.

---

## A. Sans machine virtuelle (un PC suffit)

**Il faut** : Windows, Linux ou macOS ; **Python 3.10 ou plus (3.12 recommandé)** ; Internet **la première fois seulement**. Aucun droit administrateur.

**Windows**
1. Télécharger le dépôt (*Code → Download ZIP*) et **décompresser entièrement** le ZIP (clic droit → *Extraire tout…*).
2. **Double-clic sur `demarrer.bat`.** Si Windows affiche « Windows a protégé votre ordinateur » : *Informations complémentaires → Exécuter quand même*.
3. **Première fois** : la fenêtre noire installe PyQt6 (1 à 2 minutes). **Ne pas la fermer.** Les lancements suivants sont immédiats.
4. L'interface s'ouvre (un serveur local avec base SQLite tourne en arrière-plan). **Fermer l'interface** arrête aussi ce serveur. Les données sont dans `donnees/demo.db`.

**Linux / macOS** : `bash demarrer.sh` (Linux : si la fenêtre ne s'ouvre pas, `sudo apt install -y libxcb-cursor0`).

**Windows Defender signale `Trojan:Script/Wacatac.B!ml` sur le ZIP** : faux positif connu (le suffixe `!ml` = détection
automatique, pas un virus identifié) déclenché par `demarrer.bat`, surtout pour un ZIP téléchargé depuis une messagerie.
Le fichier est lisible (bloc-notes) ; le plus simple est de récupérer le projet avec `git clone`.

**Python absent** (sans être administrateur) : [python.org/downloads](https://www.python.org/downloads/) → installeur → **« Install Now »**, ou Microsoft Store. `demarrer.bat` retrouve Python même hors du PATH.

| Situation sur le poste | Ce que fait `demarrer.bat` |
|---|---|
| Python absent | affiche la marche à suivre ci-dessus et s'arrête |
| Python installé mais absent du PATH | le retrouve dans `%LocalAppData%\Programs\Python` |
| Dossier en lecture seule (clé USB, dossier réseau) | environnement dans `%LocalAppData%\carrefour-connecte`, données dans `%TEMP%\carrefour-donnees` |
| Internet derrière un proxy | avant de lancer : `set HTTPS_PROXY=http://serveur:port` |
| **Pas d'Internet** | utilise le dossier `wheels` s'il existe (ci-dessous) |

**Poste sans Internet** : sur un PC connecté, avec **la même version de Python** que le poste cible :
`py -m pip download -r requirements.txt --only-binary=:all: -d wheels`, puis copier le dossier `wheels` à côté de `demarrer.bat`.

---

## B. Sur des VM quelconques (1, 2, 3 VM ou plus)

`install.sh` **ne modifie jamais le réseau** des VM dans ce mode : il utilise les adresses qu'elles ont déjà.

**Prérequis de chaque VM** : Debian 12 / 13 ou Ubuntu 24.04, un compte avec `sudo`, accès Internet (apt, pip, GitHub).
Derrière un proxy : `export http_proxy=http://serveur:port https_proxy=http://serveur:port` puis utiliser `sudo -E` au lieu de `sudo`.

**Étape 0 – sur chaque VM** : récupérer le projet et noter son adresse IP.
```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Nail067/SAE3.02-R3.09-Groupe-A113.git carrefour-connecte && cd carrefour-connecte
ip -br a          # noter l'adresse IP de la VM (ex. 10.0.0.5)
```

### B1. Une seule VM (base + serveur ensemble)
```bash
sudo ./install.sh tout
```

### B2. Deux VM ou plus (base et serveur séparés)
Avec `<IP_BASE>` = adresse de la VM base, `<IP_SERVEUR>` = adresse de la VM serveur
(remplacer **tout** `<…>`, chevrons compris). Vérifier d'abord que les VM se voient : `ping <IP_BASE>` depuis la VM serveur.
```bash
# 1) VM base, EN PREMIER
sudo ./install.sh database --serveur <IP_SERVEUR>
#    -> affiche à la fin la commande exacte à lancer sur la VM serveur, avec le mot de passe généré :
# 2) VM serveur : copier-coller cette commande (--jeton facultatif : impose un jeton facile à taper)
sudo ./install.sh serveur --db <IP_BASE> --mdp <MOT_DE_PASSE_AFFICHÉ> --jeton <JETON>
```
L'installation du serveur doit finir par « tout est conforme » **et « (moteur : mariadb) »**.
Ensuite, les deux VM peuvent être (re)démarrées **dans n'importe quel ordre** : si la base n'est pas encore prête,
le serveur démarre quand même et la rejoint dès qu'elle répond ; rien n'est perdu entre-temps (section 7).

Testé : PC (interface) + VM serveur `192.168.56.102` + VM base `192.168.56.104` (Debian 12, VirtualBox).
Pour reproduire ce montage avec VirtualBox : [annexe « Préparer deux VM VirtualBox »](#annexe--préparer-deux-vm-virtualbox-pour-tester).

### Résultat attendu (VM serveur)
L'installation se termine par un auto-test (« tout est conforme ») et un encadré :
```
Serveur prêt :  10.0.0.6:5050      (adresse à utiliser depuis le PC ; les autres adresses de la VM sont listées dessous)
Jeton IHM    :  k3J9xQ2mLp8vT0aZ
Sur le PC (Windows) :  demarrer.bat vm 10.0.0.6 k3J9xQ2mLp8vT0aZ
```
`sudo ./scripts/infos.sh` réaffiche ces informations à tout moment.

### Lancer l'interface
- **Sur le PC (Windows)** : dans le dossier du projet, `demarrer.bat vm <IP_SERVEUR> <JETON>` (invite de commandes ou PowerShell : `.\demarrer.bat vm …`).
- **Sur le PC ou une 3e VM avec bureau (Linux)** : `bash demarrer.sh vm <IP_SERVEUR> <JETON>` (au besoin `sudo apt install -y python3-venv libxcb-cursor0`).
- L'adresse et le jeton sont mémorisés : ensuite `demarrer.bat vm` suffit. On peut aussi les changer dans l'onglet **Paramètres** de l'interface.
- Contrôle sans interface : `python scripts/check_server.py --host <IP_SERVEUR> --token <JETON>`.

### Options utiles
| Option | Effet |
|---|---|
| `--dry-run` | affiche ce qui serait fait, sans rien modifier |
| `--pare-feu` | ferme tous les ports sauf 5050 (serveur), 3306 depuis la VM serveur (base) et SSH ; à faire en dernier |
| `--jeton <J>` | impose le jeton au lieu de le générer |

Relancer `install.sh` est sans risque : le mot de passe et le jeton déjà générés sont réutilisés.

### Si ça ne marche pas
| Message | Solution |
|---|---|
| `la base ne répond pas sur <IP>:3306` | installer d'abord la VM base ; vérifier `ping <IP_BASE>` depuis la VM serveur |
| `Connexion à la base impossible` | mauvais mot de passe ou mauvaise adresse serveur déclarée : relancer sur la VM base la commande affichée, puis la commande `serveur` qu'elle donne |
| `connecteur Python MariaDB impossible à installer` | système trop ancien (Ubuntu 22.04, Debian 11) : le serveur fonctionne quand même avec SQLite |
| Journal du serveur : `MariaDB indisponible … nouvelle tentative` | VM base éteinte ou MariaDB arrêtée : le serveur réessaie seul toutes les 10 s, les postes IHM gardent les événements en attente |
| `ssh: … Connection timed out` | VM injoignable depuis le PC : vérifier son adresse (`ip -br a`) et sa carte réseau (annexe) |
| L'interface affiche « Serveur déconnecté » | `ping <IP_SERVEUR>` depuis le PC ; port 5050 bloqué par un pare-feu ? (`Test-NetConnection <IP> -Port 5050`) |
| `jeton invalide` | recopier le jeton de `sudo ./scripts/infos.sh` (ou dans l'onglet Paramètres) |
| `bash: ...\r: command not found` | fins de ligne Windows : cloner avec Git (pas de copie depuis Windows), ou `sed -i 's/\r$//' install.sh scripts/*.sh` |

---

## 1. Architecture

```
 IHM PyQt6 (PC ou VM avec bureau) ──TCP 5050, JSON──► Serveur (server/) ──TCP 3306──► Base MariaDB
                                                        repli SQLite si MariaDB est injoignable
```

| Dossier / fichier | Rôle |
|---|---|
| `client/` | IHM PyQt6 : `main.py` (point d'entrée), `main_window.py`, `scene.py` (QGraphicsScene), `simulation.py` (moteur), `network.py` (QThread + socket), `outbox.py` (file d'attente locale des événements) |
| `server/` | `server.py` (sockets + select), `database.py` (MariaDB, repli SQLite), `schema.sql` (5 tables + vue chronologie) |
| `common/` | code partagé : `protocol.py` (trames JSON délimitées par `\n`), `config.py` (lecture de `deploy/carrefour.conf`) |
| `install.sh`, `scripts/` | installation d'une VM ; `infos.sh` (adresse et jeton), `check_server.py` (vérification de bout en bout), pare-feu, sauvegarde |
| `run_demo.py`, `demarrer.bat`, `demarrer.sh` | démarrage en une commande (démonstration locale ou IHM vers une VM) |
| `deploy/` | réseau VirtualBox de l'équipe (`carrefour.conf`, modèles réseau, service systemd, `FICHE_PROCEDURALE.md`, `DEPLOIEMENT_RESEAU.md`) |
| `.idea/runConfigurations/` | configurations de lancement PyCharm |

Règle de thread-safety : le thread réseau (`QThread`) n'agit **jamais** sur l'IHM ; tout passe par des `pyqtSignal`.

## 2. Développer avec PyCharm

1. *File → Open…* sur le dossier du projet.
2. *Settings → Project → Python Interpreter → Add Interpreter → Virtualenv → New* (Python 3.10 à 3.14).
3. `pip install -r requirements.txt` dans le terminal intégré (le connecteur MariaDB n'est installé que sous Linux).
4. Configurations (liste en haut à droite) : `Demo (tout-en-un)` (serveur local + IHM), `IHM (vers les VM)` (adresse et jeton de `deploy/carrefour.local.conf` ou de l'onglet Paramètres), `Test serveur (VM)`.

## 3. Utilisation de l'IHM

1. Choisir le **type de carrefour** (carrefour à 4 voies à feux, ou rond-point), le **véhicule d'urgence** et sa **branche de sortie**.
2. **Lancer la simulation** puis **Envoyer le véhicule d'urgence**.
3. Cliquer sur **Appuyer (Véhicule d'urgence)** (ou activer la demande automatique dans *Paramètres*).
4. Journal : demande → feu vert de la voie (ou arrêt des autres branches au rond-point) → franchissement → retour au cycle normal.
5. Onglets **Réseau** (trames JSON) et **Base de données** (les 5 tables + « ★ Chronologie d'une intervention »).

**V2V** : dès que l'urgence apparaît, les autres véhicules la détectent et lui cèdent le passage, sans appui sur le bouton.
**V2I** : le bouton envoie la demande au serveur, qui l'enregistre en base et met le feu au vert pour sa seule voie.
Sans serveur joignable, l'IHM passe en **mode dégradé** (décision locale), le signale dans le journal et **garde tous les événements** pour les envoyer à la reconnexion (section 7).

**Rond-point** : un véhicule ne cède le passage qu'à ceux qui arrivent sur sa zone d'insertion ; sans véhicule devant lui, il passe sans s'arrêter.

## 4. Base de données (5 tables)

| Table | Contenu |
|---|---|
| `sessions_simulation` | date, type de carrefour, régulation, densité du trafic |
| `vehicules` | voiture, camion, bus, ambulance…, direction, destination, état |
| `evenements_priorite` | heure de la demande, direction, durée, résultat (accordée / terminée…) |
| `evenements_trafic` | véhicule arrêté, embouteillage détecté, passage terminé |
| `journal_feux` | changements d'état des feux, avec la cause |

`SELECT * FROM v_chronologie WHERE id_session = 1 ORDER BY heure;` restitue une intervention :
*14:03:10 demande de priorité → 14:03:11 feux modifiés → 14:03:18 passage terminé et retour au cycle normal.*

## 5. Sécurité et secrets

- Le **mot de passe de la base** (compte `carrefour`, droits SELECT/INSERT/UPDATE/DELETE, limité à l'adresse de la VM serveur) et le **jeton des postes IHM** sont générés par `install.sh`, stockés sur les VM dans `/etc/carrefour/` (lisibles par root et par le service uniquement) et **jamais versionnés**.
- Pour imposer ses propres valeurs : `--mdp` / `--jeton`, ou `DB_PASSWORD=…` / `TOKEN=…` dans `deploy/carrefour.local.conf` (ignoré par Git).
- Le serveur refuse tout poste sans le bon jeton ; les trames invalides ou trop volumineuses ferment la connexion ; les tables lisibles sont en liste blanche.

## 6. Protocole (JSON, une trame par ligne)

| Sens | Messages |
|---|---|
| Client → Serveur | `hello` (+ jeton), `session_start`, `session_end`, `vehicle`, `vehicle_state`, `priority_request`, `priority_log`, `crossing_done`, `traffic_event`, `light_change`, `batch`, `history`, `chronology`, `ping` |
| Serveur → Client | `welcome`, `session_started`, `priority_grant`, `v2v_alert`, `ack`, `history_result`, `pong`, `error` |

Les événements de l'IHM partent dans des messages `batch` : chacun porte un numéro `n`, sa session `sess` et son heure réelle `ts` ; le serveur répond `{"type": "ack", "ref": "batch", "n": …}`. `priority_log` enregistre une priorité décidée par l'IHM pendant une coupure.

La décision de priorité **ne dépend pas de la base** : le serveur répond d'abord, puis journalise (si MariaDB est coupée, la priorité reste accordée).

## 7. Journalisation sans perte (coupure du serveur ou du réseau)

- **Pendant la coupure**, l'IHM continue : une demande de priorité sans réponse (serveur injoignable, ou pas de réponse en 2,5 s) est **accordée localement** (mode dégradé). Tous les événements (véhicules, feux, priorité, passage) sont gardés **sur le poste**, dans `donnees/ihm_en_attente.db` (SQLite), avec leur **heure réelle**. Le pied de page affiche « N en attente ».
- **À la reconnexion**, ils sont envoyés par lots ; le serveur rattache tout à **la même session** (même après un redémarrage du serveur), enregistre les heures réelles et marque la priorité « mode dégradé ». Un événement n'est retiré du poste qu'**après acquittement** par le serveur ; un lot renvoyé n'est pas enregistré deux fois.
- **Fermer l'IHM pendant la coupure** ne perd rien : la file est sur disque et part au lancement suivant.
- **Base MariaDB en panne** (serveur démarré) : le serveur n'acquitte pas, l'IHM renverra plus tard.

Démonstration : lancer une simulation, couper le serveur (`sudo systemctl stop carrefour-serveur`), envoyer l'ambulance et appuyer sur le bouton,
relancer le serveur (`sudo systemctl start carrefour-serveur`), puis onglet **Base de données → ★ Chronologie** : l'intervention y est, aux heures réelles.

## 8. Tests automatisés

```bash
python -m unittest discover -s tests -v
```
Découpage des trames TCP, rejet des trames invalides, base SQLite temporaire, configuration (dont l'absence de secret dans le dépôt),
reprise après coupure (aucune perte, aucun doublon, redémarrage du serveur, panne de base), file d'attente locale, lanceur, et moteur de simulation (intervention d'urgence complète sur chaque carrefour). Ni serveur MariaDB ni affichage nécessaires.

## 9. Dépannage (poste IHM et serveur)

| Symptôme | Solution |
|---|---|
| Pied de page « N en attente » qui ne diminue pas | serveur injoignable ou base en panne : les événements restent sur le poste et partiront dès que possible (`sudo journalctl -u carrefour-serveur -n 30`) |
| IHM « Serveur déconnecté » | serveur arrêté, mauvaise IP ou pare-feu : `sudo systemctl status carrefour-serveur` sur la VM, `Test-NetConnection <IP> -Port 5050` sur le PC |
| `jeton invalide` | `sudo ./scripts/infos.sh` sur la VM serveur, puis `demarrer.bat vm <IP> <JETON>` |
| Serveur en `sqlite` au lieu de `mariadb` | `sudo journalctl -u carrefour-serveur -n 30 --no-pager` (IP, mot de passe, connecteur) |
| « Installation de PyQt6 impossible » (PC) | vérifier Internet / proxy, ou utiliser le dossier `wheels` |
| « Visual C++ 14.0 required » (PC) | supprimer `.venv`, relancer ; sinon installer Python 3.12 |
| La fenêtre s'ouvre puis se ferme | relancer depuis une invite de commandes pour lire le message ; voir `donnees/serveur.log` |
| Tout recommencer (PC) | supprimer `.venv` (et `%LocalAppData%\carrefour-connecte`), relancer |

## 10. Périmètre de cette version

- IHM PyQt6 : **carrefour à 4 voies** (feux tricolores) et **rond-point**, véhicules d'urgence (ambulance, pompiers, police), V2V et V2I, détection d'embouteillage.
- Le schéma de base prévoit aussi les types de carrefour `T` et `Y` et la régulation `panneaux`, non utilisés par l'IHM dans cette version.
- Livrables à la racine du dépôt : `Bilan_Projet.pdf` et `IAGraphie.pdf`.

---

## Annexe : préparer deux VM VirtualBox pour tester

Seulement pour reproduire le montage à deux VM chez soi ; inutile sur des VM fournies déjà en réseau.

1. **Cloner** la VM éteinte : clic droit → *Cloner* → *Clone intégral*, politique d'adresse MAC : *Générer de nouvelles adresses MAC*
   (deux VM avec la même adresse MAC se volent leur adresse IP).
2. **Deux cartes réseau par VM** (VM éteintes), depuis PowerShell :
   ```powershell
   $vbox = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
   $ho = "VirtualBox Host-Only Ethernet Adapter"          # nom exact : & $vbox list hostonlyifs
   & $vbox modifyvm "<VM>" --nic1 nat --nic2 hostonly --hostonlyadapter2 $ho --macaddress1 auto --macaddress2 auto
   ```
   Carte 1 (NAT) : Internet. Carte 2 (réseau privé hôte) : adresse `192.168.56.x`, joignable par l'autre VM **et par le PC**.
3. **Un profil réseau par carte** dans chaque VM (sinon activer l'une désactive l'autre), en root :
   ```bash
   nmcli connection add type ethernet ifname enp0s3 con-name nat connection.autoconnect-priority 10
   nmcli connection add type ethernet ifname enp0s8 con-name hostonly connection.autoconnect-priority 10
   nmcli connection up nat; nmcli connection up hostonly
   ip -br a        # enp0s3 = 10.0.2.15, enp0s8 = 192.168.56.x
   ```
4. **SSH** depuis le PC (copier-coller possible) : `sudo apt install -y openssh-server` dans la VM, puis `ssh <utilisateur>@192.168.56.x`
   et `scp <fichier> <utilisateur>@192.168.56.x:~`. Si `sudo` est refusé : `su -` puis `usermod -aG sudo <utilisateur>`.
5. Une VM qui avait déjà reçu `install.sh tout` et devient VM serveur : `sudo systemctl disable --now mariadb` (sa base locale ne sert plus).

VM avec **une seule carte NAT** : le PC ne joint la VM que par redirection de ports (`& $vbox controlvm "<VM>" natpf1 "carrefour,tcp,,5050,,5050"`,
puis `demarrer.bat vm 127.0.0.1 <JETON>`). Dans ce cas, serveur arrêté, VirtualBox accepte puis ferme la connexion : l'interface
l'affiche simplement « déconnecté » et réessaie.
