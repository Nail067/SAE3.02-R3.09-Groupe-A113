@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
rem ====================================================================
rem Demarrage en une commande (Windows), SANS droits administrateur.
rem   demarrer.bat       demonstration complete sur ce poste (aucune VM)
rem   demarrer.bat vm IP JETON   interface seule, connectee au serveur d'une VM (IP et jeton affiches par install.sh)
rem   demarrer.bat vm            idem avec la derniere adresse et le dernier jeton utilises
rem Poste sans Internet : placer un dossier "wheels" a cote de ce fichier (voir README).
rem ====================================================================

rem --- 1. Python 3.10+ : lanceur "py", puis "python", puis installation "utilisateur" hors PATH
set "PY="
set "PYV="
for %%V in (3.12 3.13 3.14 3.11 3.10) do if not defined PY call :tester py -%%V
if not defined PY call :tester python
if not defined PY for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do if not defined PY call :tester "%%D\python.exe"
if not defined PY goto :sans_python

rem --- 2. Environnement virtuel : dans le projet, sinon dans %LocalAppData% (dossier en lecture seule, cle USB...)
set "VENV=.venv"
if exist "%VENV%\Scripts\python.exe" goto :dependances
set "VENV=%LocalAppData%\carrefour-connecte\venv"
if exist "%VENV%\Scripts\python.exe" goto :dependances
echo Premiere utilisation : preparation de l'environnement ^(1 a 2 minutes^)...
set "VENV=.venv"
"%PY%" %PYV% -m venv "%VENV%" >nul 2>nul
if exist "%VENV%\Scripts\python.exe" goto :dependances
echo Dossier du projet protege en ecriture : environnement cree dans %LocalAppData%\carrefour-connecte
set "VENV=%LocalAppData%\carrefour-connecte\venv"
"%PY%" %PYV% -m venv "%VENV%"
if not exist "%VENV%\Scripts\python.exe" goto :echec_venv

rem --- 3. Dependances (PyQt6 seulement ; --only-binary = jamais de compilation, donc pas de "Visual C++ requis")
:dependances
if exist "%VENV%\.ok" goto :lancer
"%VENV%\Scripts\python.exe" --version
if exist "wheels" goto :hors_ligne
"%VENV%\Scripts\python.exe" -m pip install -q --disable-pip-version-check --only-binary=:all: -r requirements.txt
if not errorlevel 1 goto :dependances_ok
echo Versions figees indisponibles pour votre Python : installation de la derniere version de PyQt6...
"%VENV%\Scripts\python.exe" -m pip install -q --disable-pip-version-check --only-binary=:all: PyQt6
if errorlevel 1 goto :echec_pip
goto :dependances_ok
:hors_ligne
echo Installation hors ligne depuis le dossier "wheels"...
"%VENV%\Scripts\python.exe" -m pip install -q --disable-pip-version-check --no-index --find-links=wheels --only-binary=:all: -r requirements.txt
if errorlevel 1 goto :echec_pip
:dependances_ok
echo ok> "%VENV%\.ok"

rem --- 4. Lancement
:lancer
set "ARGS="
if /i "%~1"=="vm" set "ARGS=--vm %2 %3"
"%VENV%\Scripts\python.exe" run_demo.py %ARGS%
if errorlevel 1 pause
exit /b 0

:tester
"%~1" %2 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%~1"
set "PYV=%~2"
exit /b 0

:sans_python
echo Python 3.10 ou plus recent est introuvable sur ce poste.
echo Aucun droit administrateur n'est necessaire :
echo   - installer Python depuis https://www.python.org/downloads/ avec "Install Now" ^(installation pour l'utilisateur^),
echo   - ou l'installer depuis le Microsoft Store.
echo Puis relancer ce fichier.
pause
exit /b 1

:echec_venv
echo Impossible de creer l'environnement Python ^(ni dans le projet, ni dans %LocalAppData%^).
echo Verifier l'espace disque et que Python est complet ^(module "venv"^), puis relancer.
pause
exit /b 1

:echec_pip
echo Installation de PyQt6 impossible.
echo   - Verifier la connexion Internet. Derriere un proxy : set HTTPS_PROXY=http://serveur:port puis relancer.
echo   - Sans Internet : utiliser le dossier "wheels" (voir README, section "Poste sans Internet").
echo Pour tout reprendre de zero : supprimer le dossier .venv ^(et %LocalAppData%\carrefour-connecte^).
pause
exit /b 1
