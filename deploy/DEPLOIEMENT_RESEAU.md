# Déploiement réseau : client + VM Serveur + VM Database de données
> **Installation automatique : `sudo ./install.sh database` puis `sudo ./install.sh serveur --mdp <affiché>` configurent les adresses ci-dessous et installent tout (voir `deploy/FICHE_PROCEDURALE.md`). Sur des VM quelconques : `README.md`, section B. Ce guide détaille la méthode manuelle.**

Objectif : un vrai réseau à trois machines, avec une **segmentation** (le client ne peut pas atteindre la base directement).

```
                 réseau « clients »                    réseau « données »
                 host-only 192.168.56.0/24             interne VirtualBox 10.10.10.0/24
  ┌───────────────┐       TCP 5050        ┌──────────────────┐   TCP 3306   ┌────────────────┐
  │ PC (PyCharm)  │ ────────────────────► │  VM SERVEUR      │ ───────────► │  VM DATABASE       │
  │ IHM PyQt6     │                       │  server.py       │              │  MariaDB       │
  │ 192.168.56.1  │                       │ 192.168.56.101   │              │ 10.10.10.2     │
  └───────────────┘                       │ 10.10.10.1       │              └────────────────┘
                                          └──────────────────┘
```

| Machine | Rôle | Adaptateurs VirtualBox | IP | Ports ouverts |
|---|---|---|---|---|
| PC | client IHM | carte « host-only » de VirtualBox | 192.168.56.1 | aucun |
| VM Serveur | `server.py` | 1 NAT (installation) + 2 host-only + 3 réseau interne `reseau-donnees` | 192.168.56.101 / 10.10.10.1 | 5050 et 22 depuis 192.168.56.0/24 |
| VM Database | MariaDB | 1 NAT (installation, à couper ensuite) + 2 réseau interne `reseau-donnees` | 10.10.10.2 | 3306 et 22 depuis 10.10.10.1 seulement |

Variante simple (sans segmentation) : un seul réseau host-only, la VM Database en `192.168.56.102`, et on remplace `10.10.10.x` par ces IP.

## 1. VirtualBox : réseau et machines

1. Réseau host-only : *Fichier → Outils → Gestionnaire de réseau hôte* → créer, IPv4 `192.168.56.1`, masque `255.255.255.0`, **DHCP désactivé**.
2. Créer deux VM **Debian 12** (ISO netinst) : 1 vCPU, 1 Go de RAM, 10 Go de disque chacune, noms `VM-Database` et `VM-Serveur`.
3. Paramètres → Réseau, **VM-Serveur** : adaptateur 1 = NAT ; adaptateur 2 = Réseau privé hôte ; adaptateur 3 = Réseau interne, nom `reseau-donnees`.
4. **VM-Database** : adaptateur 1 = NAT ; adaptateur 2 = Réseau interne, nom `reseau-donnees`.
5. À l'installation de Debian : cocher *serveur SSH* et *utilitaires usuels du système*, pas d'environnement de bureau. Créer un utilisateur (ex. `admin`).

## 2. Adresses IP

Sur chaque VM, copier le fichier correspondant de `deploy/` dans `/etc/network/interfaces` (adapter les noms d'interfaces avec `ip -br link`), puis `sudo systemctl restart networking`.

- VM Serveur : `deploy/interfaces.vm-serveur`
- VM Database : `deploy/interfaces.vm-database`

Tests : depuis la VM Serveur `ping -c2 10.10.10.2` ; depuis le PC `ping 192.168.56.101` ; depuis le PC **`ping 10.10.10.2` doit échouer** (segmentation).

## 3. Copier le projet

```bash
# Depuis le PC (PowerShell ou terminal) : vers la VM Serveur
scp carrefour-connecte.zip admin@192.168.56.101:~
# Sur la VM Serveur : décompresser, puis envoyer vers la VM Database (via le réseau données)
sudo apt install -y unzip && unzip carrefour-connecte.zip
scp carrefour-connecte.zip admin@10.10.10.2:~       # puis unzip sur la VM Database
```
(ou `git clone` sur chaque VM grâce à l'adaptateur NAT).

## 4. Installer la VM Database (en premier)

```bash
cd carrefour-connecte
sudo ./scripts/vm_database_setup.sh 10.10.10.2 10.10.10.1 'MotDePasseFort'
sudo ./scripts/vm_database_firewall.sh 10.10.10.1
```
Ensuite, dans VirtualBox, **décocher « Câble connecté » de l'adaptateur 1 (NAT) de la VM Database** : elle n'a plus d'accès Internet, seulement la VM Serveur.
Pour une mise à jour future, reconnecter temporairement le câble.

## 5. Installer la VM Serveur

```bash
cd carrefour-connecte
sudo ./scripts/vm_serveur_setup.sh 10.10.10.2 'MotDePasseFort' 'jeton-secret'
sudo ./scripts/vm_serveur_firewall.sh 192.168.56.0/24
```
Le script crée le service `carrefour-serveur` (démarrage automatique) et lance un auto-test. Vérifier : `systemctl status carrefour-serveur`.

## 6. Le client (PC, PyCharm)

1. `demarrer.bat vm 192.168.56.101 jeton-secret` (ou configuration PyCharm `IHM (vers les VM)` avec `CARREFOUR_HOST` / `CARREFOUR_TOKEN`, ou onglet *Paramètres* de l'IHM).
2. Configuration `Test serveur (VM)` ou : `python scripts/check_server.py --host 192.168.56.101 --token jeton-secret` doit tout valider, moteur = `mariadb`.

## 7. Recette réseau (à reprendre dans le bilan)

| # | Test | Commande | Résultat attendu |
|---|---|---|---|
| 1 | PC → VM Serveur | `ping 192.168.56.101` | réponse |
| 2 | VM Serveur → VM Database | `ping -c2 10.10.10.2` | réponse |
| 3 | PC → VM Database (interdit) | `ping 10.10.10.2` | échec |
| 4 | Port IHM ouvert | `Test-NetConnection 192.168.56.101 -Port 5050` | `TcpTestSucceeded : True` |
| 5 | Base inaccessible depuis le PC | `Test-NetConnection 10.10.10.2 -Port 3306` | échec |
| 6 | Base accessible depuis la VM Serveur | `mariadb -h 10.10.10.2 -u carrefour -p carrefour -e "SHOW TABLES;"` | 5 tables + 1 vue |
| 7 | Contrôle global | `python scripts/check_server.py --host 192.168.56.101 --token …` | « tout est conforme » |
| 8 | Données écrites | sur la VM Database : `sudo mariadb carrefour -e "SELECT * FROM v_chronologie ORDER BY heure;"` | la chronologie de l'intervention |
| 9 | Jeton invalide | IHM avec un mauvais jeton | « jeton invalide », connexion refusée |
| 10 | Reprise après coupure | `sudo systemctl restart mariadb` sur la VM Database, puis relancer une simulation | le serveur se reconnecte seul |

## 8. Exploitation

- Journal en direct : `journalctl -u carrefour-serveur -f`
- Sauvegarde : `sudo ./scripts/backup_db.sh` (VM Database)
- Instantanés VirtualBox de chaque VM une fois le réseau validé ; démarrer **la VM Database d'abord, puis la VM Serveur**.

## 9. Dépannage

| Symptôme | Piste |
|---|---|
| Interface sans IP | nom d'interface différent : `ip -br link`, corriger `/etc/network/interfaces` |
| Le PC ne voit pas 192.168.56.101 | adaptateur 2 de la VM Serveur mal réglé, ou adresse du réseau host-only différente |
| VM Serveur → VM Database impossible | même nom de réseau interne (`reseau-donnees`) sur les deux VM ; câbles connectés |
| `Access denied for user 'carrefour'` | le compte est lié à l'IP `10.10.10.1` : relancer `vm_database_setup.sh` avec les bonnes IP |
| Serveur en `sqlite` | MariaDB injoignable : lire `journalctl -u carrefour-serveur` |
| IHM « Serveur déconnecté » | pare-feu : `sudo ufw status` ; le PC doit être dans `192.168.56.0/24` |
