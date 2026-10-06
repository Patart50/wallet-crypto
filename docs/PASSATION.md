# Passation — wallet-crypto (6 octobre 2026, 19 h 30)

À lire après `claude/PROGRAMME.md`. Compléter avec `claude/wallet-crypto/SPEC.md` et `DECISIONS.md` (aussi dans `docs/` du dépôt).

## Le projet

Suivi de patrimoine crypto auto-hébergé en Python (NiceGUI, SQLite), pour utilisateurs avertis : wallets HL / EVM / Solana / Bitcoin, patrimoine sans double comptage, staking intégré (HYPE, WCT, manuel), hold avec PMP, trades Hyperliquid et trades saisis à la main. Chaque utilisateur fournit sa clé Alchemy. Dérivé du module wallet de Titan, réécrit sans dépendance (wallet D-003). Auteur : « Arnaud (Patart50) », jamais de nom de famille.

- Dépôt : https://github.com/Patart50/wallet-crypto (AGPL-3.0). Pas de site statique : pas de Pages.
- Méthode : `add_repo` Patart50/wallet-crypto en push, une branche et une PR par jalon, PR via `env -u GH_TOKEN gh api repos/Patart50/wallet-crypto/pulls`. Avant chaque PR : `ruff check src tests`, `ruff format --check src tests`, `pytest`. Tags et releases : Arnaud.
- Clone superficiel : après `git push -u`, `git config --add remote.origin.fetch '+refs/heads/<b>:refs/remotes/origin/<b>'` puis `git fetch origin <b>`.
- Environnement de Claude : **aucun accès réseau** à Hyperliquid, Alchemy, mempool.space ni Binance (proxy). Tout est testé sur des réponses fictives (`tests/fixtures/`, `FakeHttp` dans `tests/conftest.py`) calquées sur le code Titan qui tourne en réel. La vérification sur données réelles est à faire par Arnaud.
- Pour lire commun-crypto : `git clone --depth 1` public suffit.

## Où on en est

- **J1 en PR #1** (branche `j1-moteur`) : moteur en `Decimal`, sources (registre extensible), base SQLite, synchronisation avec verrou, CLI, CI. 89 tests.
- Reste à Arnaud : relire et fusionner ; **trancher D-013** (il a demandé `float`, Claude a gardé `Decimal` et expliqué pourquoi) ; tester en réel `wallet-crypto sync` avec ses adresses (sans jamais les commiter) et remonter les écarts.

## Repères dans le code

- `src/wallet_crypto/core/` : `assets.py` (lignes, valorisation), `portfolio.py`, `staking.py`, `hold.py`, `trades.py`, `manual_trades.py`, `gains.py`.
- `src/wallet_crypto/sources/` : `base.py` (registre, `BalanceResult`, `HistoryBatch`), `http.py`, `hyperliquid.py`, `alchemy.py` (EVM, Solana, WCT), `mempool.py`, `binance.py`.
- `src/wallet_crypto/db/` : `models.py` (`DecimalText`, `JsonText`), `store.py`.
- `sync.py` (orchestrateur), `prices.py` (prix courants), `lock.py`, `config.py`, `log.py` (masquage), `security.py` (refus des secrets, contrôle des adresses), `support.py`, `fmt.py`, `cli.py`.

## J2 (prochain jalon)

Interface NiceGUI (onglets Wallets, Staking, Hold, Trades, Graphiques, Réglages, À propos), `wallet-crypto serve` sur 127.0.0.1:8090, synchronisation automatique en tâche de fond, prix historiques Binance avec cache SQLite (pour `gains.py`), QR codes de don (`segno`), Dockerfile + compose (non root), saisie de la clé Alchemy dans Réglages.

## Points ouverts

- D-013 : `Decimal` ou `float` (à confirmer par Arnaud).
- D-004 : consommation Alchemy réelle d'une synchronisation, à mesurer.
- Formats d'API non vérifiés en réel depuis l'environnement de Claude : `userAbstraction` (forme de la réponse), réseaux à activer dans l'app Alchemy.
- Alembic avant la v1.0 (D-018).

## Référence

Code source Titan fourni dans la conversation du 6 oct. 2026 : `wallet_models.py` V3.7, `wallet_sync.py` V3.3, `wallet_ui.py` V3.12, `wallet_charts.py` V1.1. Ne jamais commiter les adresses, clés ou données réelles d'Arnaud.
