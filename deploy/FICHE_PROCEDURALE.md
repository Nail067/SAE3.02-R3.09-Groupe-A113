# Fiche procédurale – Mise en production du carrefour connecté (GitHub → VM Database → VM Serveur → IHM)

**SAÉ 3.02 – Groupe A113** – BENCHEKCHOU Nail-Omar & LEMASSON Ewan

> À suivre dans l'ordre. Chaque étape indique **où** la faire, **les commandes**, **le résultat attendu** et **quoi faire en cas d'échec**.
> Cette fiche décrit le **réseau VirtualBox segmenté de l'équipe**. Sur des VM quelconques (évaluation, nombre de VM imposé), suivre plutôt la **section B du `README.md`**.
> Dépôt : `https://github.com/Nail067/SAE3.02-R3.09-Groupe-A113`. **Aucune adresse IP n'est à saisir** : le plan d'adressage est dans `deploy/carrefour.conf`. Le mot de passe de la base et le jeton sont **générés** par `install.sh` et affichés à l'écran (voir l'Annexe C pour imposer les vôtres).

## Chemin express (pour quelqu'un qui découvre le projet)

| Je veux… | Je fais… |
|---|---|
| **Voir le projet fonctionner** (sans VM) | Installer Python, télécharger le projet, double-clic sur **`demarrer.bat`** (Windows) ou `bash demarrer.sh` (Linux/macOS) |
| **Déployer le réseau complet** (2 VM) | Sur chaque VM : `git clone`, puis `sudo bash install.sh database` / `sudo bash install.sh serveur --mdp <affiché>`, puis sur le PC `demarrer.bat vm 192.168.56.101 <JETON>` |
| **Déployer sur des VM quelconques** | `README.md`, section B (`install.sh tout`, ou `database --serveur` / `serveur --db`) |
| **Comprendre ou modifier** | Ouvrir le dossier dans PyCharm et lancer la configuration `Demo (tout-en-un)` |

Le reste de cette fiche détaille le réseau complet, étape par étape.

## Principe

Le projet **configure tout seul** les VM : le plan d'adressage est dans **`deploy/carrefour.conf`** ; le mot de passe de la base et le jeton sont générés à l'installation (jamais dans le dépôt).
Sur une VM propre, on récupère le projet puis on lance **une seule commande** (`sudo ./install.sh database` ou `serveur`) : adresses IP, logiciels, base, service et vérification.
L'IHM lit les mêmes valeurs par défaut. **Aucune adresse n'est à saisir ni à modifier.**

| Phase | Où | Objectif |
|---|---|---|
| P0 | PC | Prérequis (Git, Python, VirtualBox) |
| P1 | PC | Publier le projet sur GitHub |
| P2 | VirtualBox | Réseau et 2 VM propres avec les bonnes cartes |
| P3 | VM Database et VM Serveur | Importer le projet |
| P4 | VM Database | `sudo ./install.sh database` |
| P5 | VM Serveur | `sudo ./install.sh serveur --mdp <MOT_DE_PASSE>` |
| P6 | PC | Lancer l'interface (aucune adresse à saisir) |
| P7 | VM Database et VM Serveur | Pare-feu et isolement de la base |
| P8 | PC + VM | Recette réseau et checklist de rendu |
| Annexes | | Mise à jour, retour arrière, changer le plan d'adressage, dépannage |

Plan d'adressage par défaut : PC `192.168.56.1` · VM Serveur `192.168.56.101` (clients) et `10.10.10.1` (données) · VM Database `10.10.10.2`.

---

## P0 – Prérequis sur le PC (Windows)

| # | Action | Vérification |
|---|---|---|
| 0.1 | Installer **Git** : https://git-scm.com ou `winget install --id Git.Git -e` | `git --version` |
| 0.2 | Installer **Python 3.12** (cocher « Add python.exe to PATH ») | `python --version` |
| 0.3 | Installer **VirtualBox** et télécharger l'ISO **Debian 12** (netinst) | VirtualBox s'ouvre |
| 0.4 | Créer un compte **GitHub** | connexion sur github.com |
| 0.5 | Identité Git (une seule fois) | `git config --global user.name "Prénom Nom"` puis `git config --global user.email "mail@exemple.fr"` |

Si `python` répond « chemin d'accès introuvable » : désactiver les alias dans *Paramètres → Applications → Paramètres avancés → Alias d'exécution d'application* (`python.exe`, `python3.exe`), ou utiliser `py`.

---

## P1 – Publier le projet sur GitHub (PC)

**1.1 Créer le dépôt** sur github.com : *New repository* → nom `SAE302-A113-carrefour-connecte` → **Public** (exigé par le sujet) → ne rien cocher (ni README, ni .gitignore) → *Create repository*.

**1.2 Vérifier qu'aucun secret ne part** (dans le dossier du projet, PowerShell) :
```powershell
cd C:\chemin\vers\carrefour-connecte
type .gitignore
Select-String -Path deploy\carrefour.conf,.idea\runConfigurations\*.xml -Pattern "DB_PASSWORD|TOKEN="
```
Attendu : `.gitignore` contient `venv/`, `*.db`, `.idea/*` et `deploy/carrefour.local.conf`. **Aucune ligne** trouvée par `Select-String`.

> Règle : **aucun mot de passe ni jeton dans le dépôt.** Les valeurs locales (adresse du serveur, jeton) vont dans `deploy/carrefour.local.conf`, ignoré par Git.

**1.3 Rendre les scripts exécutables dans Git** (sinon ils perdent leur droit d'exécution sous Windows) :
```powershell
git init -b main
git add .
git update-index --chmod=+x scripts/vm_database_setup.sh scripts/vm_serveur_setup.sh scripts/vm_database_firewall.sh scripts/vm_serveur_firewall.sh scripts/backup_db.sh scripts/infos.sh install.sh scripts/check_server.py
git ls-files -s scripts | findstr 100755
```
Attendu : les 6 scripts de `scripts/` listés avec `100755` ; vérifier `install.sh` avec `git ls-files -s install.sh`.

**1.4 Premier envoi**
```powershell
git commit -m "Version initiale : IHM PyQt6, serveur, base MariaDB, scripts de déploiement"
git remote add origin https://github.com/Nail067/SAE3.02-R3.09-Groupe-A113.git
git push -u origin main
```
Une fenêtre du navigateur demande de se connecter à GitHub (Git Credential Manager) : accepter. GitHub n'accepte plus le mot de passe du compte ; sinon créer un *Personal Access Token* (*Settings → Developer settings → Personal access tokens*, droit `repo`) et l'utiliser à la place du mot de passe.

**1.5 Marquer la version et partager**
```powershell
git tag -a v1.0 -m "Version livrable"
git push origin v1.0
```
Sur GitHub : *Settings → Collaborators* → ajouter le binôme.

**Alternative PyCharm** : *Git → Create Git Repository…*, puis *Git → GitHub → Share Project on GitHub* (compte GitHub à renseigner dans *Settings → Version Control → GitHub*).

**Contrôle** : ouvrir `https://github.com/Nail067/SAE3.02-R3.09-Groupe-A113` : le `README.md` s'affiche à la racine, avec les dossiers `client`, `server`, `common`, `scripts`, `deploy`, `tests`.

Échecs courants : `rejected` → `git pull origin main --rebase` puis `git push`. `Authentication failed` → utiliser un token (voir 1.4).

---

## P2 – Créer le réseau et les 2 VM dans VirtualBox (PC)

> « **VM Database** » = la machine virtuelle qui héberge la **base de données** MariaDB. « **VM Serveur** » = celle qui exécute le programme `server.py`.
> Les deux se créent de la même façon ; seuls le nom et les cartes réseau changent.

### 2.1 Télécharger l'ISO Debian 12
https://www.debian.org/distrib/netinst → **amd64** → fichier `debian-12.x.x-amd64-netinst.iso` (environ 600 Mo).

### 2.2 Créer le réseau « clients » (une seule fois)
VirtualBox → *Fichier → Outils → Gestionnaire de réseau hôte* (ou *Network Manager*) → **Créer** :
IPv4 `192.168.56.1` · masque `255.255.255.0` · **serveur DHCP désactivé** → *Appliquer*.

### 2.3 Créer la VM **VM-Database**
1. *Machine → Nouvelle…*
2. **Nom** : `VM-Database` · **Image ISO** : choisir l'ISO Debian · Type `Linux` · Version `Debian (64-bit)` · **cocher « Skip Unattended Installation »** (installation manuelle, on contrôle chaque choix) → *Suivant*.
3. **Matériel** : mémoire `1024` Mo · processeurs `1` → *Suivant*.
4. **Disque dur** : *Créer un disque dur virtuel maintenant* · `10` Go → *Suivant* → *Terminer*.
5. **Avant de démarrer** : clic droit sur la VM → *Configuration → Réseau* :

| Onglet | Activer la carte | Mode d'accès réseau | Nom |
|---|---|---|---|
| Adaptateur 1 | oui | **NAT** | |
| Adaptateur 2 | oui | **Réseau interne** | `reseau-donnees` |

6. *OK*.

### 2.4 Créer la VM **VM-Serveur**
Mêmes étapes 1 à 4, avec le nom `VM-Serveur`. Puis *Configuration → Réseau* :

| Onglet | Activer la carte | Mode d'accès réseau | Nom |
|---|---|---|---|
| Adaptateur 1 | oui | **NAT** | |
| Adaptateur 2 | oui | **Réseau privé hôte** | le réseau créé en 2.2 |
| Adaptateur 3 | oui | **Réseau interne** | `reseau-donnees` (même nom que sur VM-Database) |

> **Important** : l'ordre des adaptateurs compte. Le script `install.sh` reconnaît les cartes par leur ordre : la 1re = NAT (Internet), puis le réseau privé hôte (VM Serveur seulement), puis le réseau interne `reseau-donnees`. Il ne faut **pas** configurer les adresses à la main : `install.sh` s'en charge.

### 2.5 Installer Debian sur chaque VM (écran par écran)
Démarrer la VM (bouton *Démarrer*). Dans le menu de l'installeur choisir **Install** (mode texte). Naviguer avec les flèches, `Tab` et `Entrée`.

| Écran | Choix |
|---|---|
| Langue / pays / clavier | Français · France · Français |
| *Primary network interface* (VM-Serveur seulement) | la **première** (`enp0s3`, celle du NAT) |
| Nom de machine | `database-carrefour` (VM-Database) ou `serveur-carrefour` (VM-Serveur) |
| Domaine | laisser vide |
| **Mot de passe root** | **laisser vide** (l'utilisateur `admin` recevra alors automatiquement `sudo`) |
| Nom complet / identifiant / mot de passe | `admin` + un mot de passe à retenir |
| Partitionnement | *Assisté – utiliser un disque entier* → disque proposé → *Tout dans une seule partition* → *Terminer le partitionnement* → **Oui** (écrire les changements) |
| Miroir | France → `deb.debian.org` · proxy : vide |
| Enquête de popularité | Non |
| **Logiciels à installer** | **décocher** « environnement de bureau Debian » et « GNOME » ; **cocher** « serveur SSH » et « utilitaires usuels du système » (barre d'espace pour cocher) |
| GRUB | Oui → disque `/dev/sda` |
| Fin | *Continuer* : la VM redémarre sur Debian |

### 2.6 Premier démarrage et contrôle
Se connecter avec `admin`, puis :
```bash
sudo whoami          # doit répondre : root
ip -br a             # l'interface du NAT (enp0s3) a une adresse en 10.0.2.x
ping -c2 deb.debian.org
```
Échec de `sudo whoami` (« admin n'est pas dans le fichier sudoers ») : le mot de passe root avait été renseigné. Corriger avec `su -` puis `apt install -y sudo && usermod -aG sudo admin`, puis se déconnecter/reconnecter.

**Faire un instantané** (*Machine → Prendre un instantané*, nom « Debian installé ») sur chaque VM : on pourra y revenir en cas d'erreur.

### 2.7 (Facultatif) Se connecter en SSH depuis le PC plutôt que dans la console
Une fois les VM installées (P4 et P5), depuis PowerShell :
```powershell
ssh admin@192.168.56.101                          # VM-Serveur
ssh -J admin@192.168.56.101 admin@10.10.10.2      # VM-Database, en passant par la VM-Serveur
```

---

## P3 – Importer le projet sur les deux VM (sans aucune adresse à configurer)

Les VM propres ont Internet par la carte **NAT** (adresse automatique `10.0.2.x`) : c'est suffisant pour importer le projet.

**Option A – depuis GitHub (recommandée)** : sur **chaque** VM, connecté en `admin` :
```bash
sudo apt update && sudo apt install -y git
cd ~
git clone https://github.com/Nail067/SAE3.02-R3.09-Groupe-A113.git carrefour-connecte
cd carrefour-connecte && git log --oneline -1
```

**Option B – depuis le zip, sans GitHub** : redirection de port de la carte NAT (une seule fois par VM) :
*VirtualBox → VM → Configuration → Réseau → Adaptateur 1 → Avancé → Redirection de ports* → ajouter

| VM | Nom | Protocole | IP hôte | Port hôte | Port invité |
|---|---|---|---|---|---|
| VM-Serveur | ssh | TCP | 127.0.0.1 | 2201 | 22 |
| VM-Database | ssh | TCP | 127.0.0.1 | 2202 | 22 |

Puis depuis le PC (PowerShell) et sur chaque VM :
```powershell
scp -P 2201 .\carrefour-connecte.zip admin@127.0.0.1:~
scp -P 2202 .\carrefour-connecte.zip admin@127.0.0.1:~
```
```bash
sudo apt install -y unzip && unzip carrefour-connecte.zip && cd carrefour-connecte
```
(`ssh -p 2201 admin@127.0.0.1` permet aussi de travailler depuis le terminal du PC.)

Vérifier : `ls install.sh scripts deploy/carrefour.conf` répond sans erreur. Si « Permission denied » à l'exécution : `chmod +x install.sh scripts/*.sh scripts/*.py`.

---

## P4 – VM Database (à faire en premier)

```bash
cd ~/carrefour-connecte
sudo ./install.sh database --dry-run     # facultatif : montre ce qui va être configuré, sans rien modifier
sudo ./install.sh database
```
Le script :
1. repère les cartes réseau (1re = NAT, puis la carte du réseau interne) et leur donne `10.10.10.2/24` ;
2. installe MariaDB, la fait écouter sur `10.10.10.2`, charge `server/schema.sql` (5 tables + vue) ;
3. crée le compte `carrefour` limité à la VM Serveur (`SELECT/INSERT/UPDATE/DELETE`).

Attendu à la fin : `tables présentes : 5/5`, **`Base prête : 10.10.10.2:3306`**, puis la ligne à lancer sur la VM Serveur :
`sudo ./install.sh serveur --mdp <MOT_DE_PASSE>` (mot de passe généré ; à recopier).
```bash
ip -br a                                       # la carte du réseau interne porte 10.10.10.2/24
sudo mariadb carrefour -e "SHOW TABLES;"       # 5 tables + v_chronologie
```

## P5 – VM Serveur

```bash
cd ~/carrefour-connecte
sudo ./install.sh serveur --dry-run      # facultatif
sudo ./install.sh serveur --mdp <MOT_DE_PASSE>     # la ligne exacte est affichée à la fin de P4
```
Le script :
1. configure `192.168.56.101/24` (réseau clients) et `10.10.10.1/24` (réseau données) ;
2. attend que la VM Database réponde sur `10.10.10.2:3306` (jusqu'à 1 minute) ;
3. installe le serveur Python, le service `carrefour-serveur` (démarrage automatique) et lance un auto-test complet.

Attendu : « tout est conforme », puis un encadré **`Serveur prêt : 192.168.56.101:5050`** avec le **jeton** et la commande `demarrer.bat vm …` à lancer sur le PC.
```bash
systemctl status carrefour-serveur --no-pager             # active (running)
sudo journalctl -u carrefour-serveur -n 5 --no-pager      # « Base de données : mariadb »
```

---

## P6 – Lancer l'interface sur le PC

Prérequis VirtualBox sur le PC : le réseau « host-only » en `192.168.56.1` créé en P2 (c'est la seule adresse qui relève du PC).
```powershell
git clone https://github.com/Nail067/SAE3.02-R3.09-Groupe-A113.git
cd SAE3.02-R3.09-Groupe-A113
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python scripts\check_server.py --host 192.168.56.101 --token <JETON>
demarrer.bat vm 192.168.56.101 <JETON>
```
`<JETON>` est affiché à la fin de P5 (ou `sudo ./scripts/infos.sh` sur la VM Serveur). L'adresse et le jeton sont ensuite mémorisés : `demarrer.bat vm` suffit.
Attendus : « tout est conforme » avec `moteur : mariadb` ; l'interface affiche **« Serveur connecté (192.168.56.101:5050) »** en vert et « Connectée (mariadb) ».

**Avec PyCharm** : ouvrir le dossier, créer le virtualenv, installer `requirements.txt`, lancer la configuration **`IHM (vers les VM)`**.

**Scénario de démonstration** : *Lancer la simulation* → *Envoyer le véhicule d'urgence* → *Appuyer* → onglet *Base de données* → « ★ Chronologie d'une intervention ».

---

## P7 – Pare-feu et isolement de la base (une fois tout validé)

```bash
# VM Database
sudo ./install.sh database --pare-feu     # MariaDB et SSH uniquement depuis la VM Serveur
# VM Serveur
sudo ./install.sh serveur --pare-feu      # port 5050 et SSH uniquement depuis 192.168.56.0/24
```
Puis dans VirtualBox : VM-Database → Réseau → Adaptateur 1 (NAT) → **décocher « Câble connecté »** : la base n'est plus joignable que par la VM Serveur.
> Après le pare-feu, la redirection de port NAT (Option B de P3) ne permet plus de se connecter en SSH ; utiliser la console VirtualBox ou `ssh admin@192.168.56.101` depuis le PC.

---

## P8 – Recette réseau et checklist de rendu

| # | Test | Commande | Attendu |
|---|---|---|---|
| 1 | PC → VM Serveur | `ping 192.168.56.101` | réponse |
| 2 | VM Serveur → VM Database | `ping -c2 10.10.10.2` | réponse |
| 3 | PC → VM Database (interdit) | `ping 10.10.10.2` | échec |
| 4 | Port IHM | `Test-NetConnection 192.168.56.101 -Port 5050` | `TcpTestSucceeded : True` |
| 5 | Base fermée au PC | `Test-NetConnection 10.10.10.2 -Port 3306` | échec |
| 6 | Base ouverte au serveur | `mariadb -h 10.10.10.2 -u carrefour -p carrefour -e "SHOW TABLES;"` (VM Serveur) | 5 tables + 1 vue |
| 7 | Contrôle global | `python scripts\check_server.py --host 192.168.56.101 --token <JETON>` | « tout est conforme » |
| 8 | Données écrites | `sudo mariadb carrefour -e "SELECT heure, evenement FROM v_chronologie ORDER BY heure;"` (VM Database) | chronologie de l'intervention |
| 9 | Mauvais jeton | `python scripts\check_server.py --host 192.168.56.101 --token faux` | « jeton invalide » |
| 10 | Redémarrage | `sudo reboot` sur la VM Serveur | `carrefour-serveur` actif sans intervention |

**Checklist du sujet** (dépôt public dont le chef de projet dépose l'URL sur Moodle)

- [ ] Dépôt GitHub **public**, URL déposée sur Moodle
- [ ] `README.md` à la racine : groupe **A113**, **BENCHEKCHOU Nail-Omar** et **LEMASSON Ewan**, installation pas à pas, usage avec exemples
- [ ] `requirements.txt` à la racine, versions exactes
- [ ] Code Python modulaire, commentaires et docstrings sur chaque fonction et classe
- [ ] `Bilan_Projet.pdf` à la racine (fonctionnalités, conclusion technique, analyse du timing)
- [ ] `IAGraphie.pdf` (ou section dans le bilan) : usage de l'IA, prompts, réflexion éthique
- [ ] Aucun mot de passe ni jeton dans le dépôt
- [ ] Installation testée **depuis un `git clone` propre**

---

## Annexe A – Mettre à jour après une modification

1. **PC** : `git add -A`, `git commit -m "description"`, `git push`.
2. **VM Serveur** : `cd ~/carrefour-connecte && git pull && sudo ./install.sh serveur` (rejouable : il recopie le code, réutilise le mot de passe et le jeton, et redémarre le service).
3. **VM Database** (seulement si `server/schema.sql` a changé) : reconnecter temporairement le câble NAT, puis
   `cd ~/carrefour-connecte && git pull && sudo ./install.sh database`, puis déconnecter le câble.
4. **PC** : `git pull`, puis relancer l'IHM.

## Annexe B – Revenir à une version précédente

```bash
cd ~/carrefour-connecte
git tag                      # liste des versions (v1.0, …)
git checkout v1.0
sudo ./install.sh serveur
git checkout main            # pour revenir à la dernière version
```
Avant toute manipulation risquée : instantané VirtualBox de chaque VM et `sudo ./scripts/backup_db.sh` sur la VM Database.

## Annexe C – Changer le plan d'adressage, le mot de passe ou le jeton

Sans toucher au fichier versionné : créer `deploy/carrefour.local.conf` (ignoré par Git) **avec les mêmes valeurs sur les deux VM et sur le PC**, par exemple :
```
IP_DATABASE=10.20.30.2
IP_SERVEUR_DONNEES=10.20.30.1
TOKEN=mon-jeton
DB_PASSWORD=UnAutreMotDePasse
```
puis relancer `sudo ./install.sh database` et `sudo ./install.sh serveur`. Ponctuellement, une variable d'environnement suffit : `CARREFOUR_TOKEN=xxx sudo -E ./install.sh serveur`.
Les valeurs de `deploy/carrefour.conf` sont des valeurs de démonstration : les remplacer pour tout usage réel.

## Annexe D – Dépannage de `install.sh`

| Message | Cause et solution |
|---|---|
| `cette VM a 1 carte(s) réseau, 2 attendues` | adaptateur manquant dans VirtualBox : VM éteinte → *Configuration → Réseau* (voir P2) |
| `la VM Database ne répond pas sur 10.10.10.2:3306` | installer d'abord la VM Database ; même nom `reseau-donnees` sur les deux VM ; câbles connectés |
| `l'adresse … n'est pas active sur …` | nom de carte erroné : `ip -br link`, puis renseigner `IFACE_CLIENTS` / `IFACE_DONNEES` dans `deploy/carrefour.local.conf` |
| `bash: ...\r: command not found` | fins de ligne Windows : `git add --renormalize .`, commit, push, puis `git pull` sur la VM |
| `Connexion à la base impossible` (pendant `install.sh serveur`) | mauvais `--mdp` : `sudo cat /etc/carrefour/db_password` sur la VM Database |
| Serveur en `sqlite` | MariaDB injoignable : `sudo journalctl -u carrefour-serveur -n 30 --no-pager` |
| Le PC ne joint pas `192.168.56.101` | réseau host-only du PC absent ou mal réglé (`192.168.56.1`, DHCP désactivé) ; adaptateur 2 de la VM Serveur |
