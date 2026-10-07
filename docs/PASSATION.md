# Passation — wallet-crypto (7 octobre 2026, 17 h)

À lire après `claude/PROGRAMME.md`. Compléter avec `claude/wallet-crypto/SPEC.md` et `DECISIONS.md` (aussi dans `docs/` du dépôt).

## Le projet

Suivi de patrimoine crypto auto-hébergé en Python (NiceGUI, SQLite), pour utilisateurs avertis : wallets HL / EVM / Solana / Bitcoin, patrimoine sans double comptage, staking intégré (HYPE, WCT, manuel), hold avec PMP, trades Hyperliquid et trades saisis à la main. Chaque utilisateur fournit sa clé Alchemy. Dérivé du module wallet de Titan, réécrit sans dépendance (wallet D-003). Auteur : « Arnaud (Patart50) », jamais de nom de famille.

- Dépôt : https://github.com/Patart50/wallet-crypto (AGPL-3.0). Pas de site statique : pas de Pages.
- Choix d'Arnaud (6 oct. 2026) : Python plutôt que navigateur, nom `wallet-crypto`, staking intégré, trades saisis à la main conservés, plateformes centralisées à prévoir, devise $ par défaut et € en option.
- Méthode : `add_repo` Patart50/wallet-crypto en push, une branche et une PR par jalon, PR via `env -u GH_TOKEN gh api repos/Patart50/wallet-crypto/pulls`. Avant chaque PR : `ruff check src tests`, `ruff format --check src tests`, `pytest`. Tags et releases : Arnaud.
- Clone superficiel : après `git push -u`, `git config --add remote.origin.fetch '+refs/heads/<b>:refs/remotes/origin/<b>'` puis `git fetch origin <b>`.
- Environnement de Claude : **aucun accès réseau** à Hyperliquid, Alchemy, mempool.space ni Binance (proxy). Tout est testé sur des réponses fictives (`tests/fixtures/`, `FakeHttp` dans `tests/conftest.py`) calquées sur le code Titan qui tourne en réel. La vérification sur données réelles est à faire par Arnaud.
- Pour lire commun-crypto : `git clone --depth 1` public suffit.

## Où on en est

- **J1 fusionné** (PR #1) : moteur en `Decimal`, sources, base, synchronisation, CLI.
- **J2 fusionné** (PR #2, #4, #5) : interface NiceGUI complète, synchronisation automatique, prix courants (5 min) et historiques (cache journalier rempli pendant la sync), mot de passe, export/import, démonstration `serve --demo`, Docker, tests de fumée de l'interface. 111 tests, CI verte (Python 3.11 et 3.13, image Docker). Vérifié dans Chromium : 7 pages en sombre, clair et mobile, aucune requête externe, aucune erreur console, QR codes décodés identiques aux adresses, navigation au clavier avec focus visible.
- **Corrections d'usage en PR** (branche `corrections-usage`), après le premier essai réel d'Arnaud sous Docker : nettoyage de l'historique des wallets supprimés (D-031, cas de l'adresse du contrat WCT saisie par erreur), positions ouvertes en haut de Trades et cases de même hauteur (D-032). 113 tests. Arnaud doit, après fusion : `git pull && sudo docker compose up -d --build`, puis Réglages → « Nettoyer l'historique ».
- Connecteurs d'autres plateformes : D-033, après la v1.0 ; plateformes à demander à Arnaud.
- D-013 validée par Arnaud (7 oct. 2026) : `Decimal` partout.
- Arnaud fait tourner l'outil en réel sous Docker depuis le 7 oct. 2026 (« tout est bon », calculs justes). Reste à lui : fusionner la PR des corrections, nettoyer son historique, remonter les écarts suivants (aucun appel réel possible depuis l'environnement de Claude).

## Repères dans le code

- `src/wallet_crypto/core/` : moteur pur (`assets`, `portfolio`, `staking`, `hold`, `trades`, `manual_trades`, `gains`).
- `src/wallet_crypto/sources/` : registre (`base.py`), `http.py`, `hyperliquid.py`, `alchemy.py`, `mempool.py`, `binance.py`.
- `src/wallet_crypto/db/` : `models.py` (`DecimalText`, `JsonText`), `store.py`.
- `sync.py` (orchestrateur), `prices.py` (prix courants), `history.py` (prix historiques), `settings.py` (réglages en base), `services.py` (tout ce que l'interface lit ou modifie, testable sans NiceGUI), `auth.py`, `backup.py`, `demo.py`, `lock.py`, `config.py`, `log.py`, `security.py`, `support.py`, `fmt.py`, `cli.py`.
- `src/wallet_crypto/ui/` : `app.py` (cadre, pages, connexion, boucle de fond, `serve`), une page par fichier, `theme.py` (CSS, palette validée), `charts.py`, `components.py`, `context.py`, `static/` (polices OFL, favicon).
- Vérification visuelle : lancer `wallet-crypto serve --demo --port 8091`, captures Playwright avec `executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"`. Pour arrêter le serveur, ne pas utiliser `pkill -f` avec un motif présent dans la commande courante (le shell se tue lui-même).
- Pièges NiceGUI : `.hidden` de Quasar est en `!important` (utiliser `wc-hide-xs`) ; l'anneau de focus des boutons passe par `box-shadow` ; un sous-processus de test doit retirer `PYTEST_CURRENT_TEST` de son environnement.

## J3 (prochain jalon, v1.0)

Migrations Alembic (D-018), revue de sécurité (D-010, D-021, D-026), vérification sur données réelles d'Arnaud, mesure de la consommation Alchemy (D-004), captures définitives, release.

## Points ouverts

- D-004 : consommation Alchemy réelle d'une synchronisation, à mesurer.
- Formats d'API non vérifiés en réel depuis l'environnement de Claude : `userAbstraction`, `candleSnapshot`, réseaux à activer dans l'app Alchemy.
- Image Docker validée par la CI uniquement (construite et lancée en non-root, racine en lecture seule) : pas de démon Docker dans l'environnement de Claude.

## Référence

Code source Titan fourni dans la conversation du 6 oct. 2026 : `wallet_models.py` V3.7, `wallet_sync.py` V3.3, `wallet_ui.py` V3.12, `wallet_charts.py` V1.1. Ne jamais commiter les adresses, clés ou données réelles d'Arnaud.
