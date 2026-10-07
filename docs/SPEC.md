# Spécification — wallet-crypto v0.3

Suivi de patrimoine crypto auto-hébergé, en Python, en français : soldes réels des wallets (Hyperliquid, EVM, Solana, Bitcoin), staking, hold avec prix moyen, trades Hyperliquid et trades saisis à la main. Public : utilisateurs avertis, à l'aise avec un terminal ou Docker. Projet frère de pmpa-crypto, dca-crypto, renfort-crypto et carnet-crypto. Toute convention est consignée dans [DECISIONS.md](DECISIONS.md).

Dérivé du module « wallet » de Titan (privé), réécrit sans aucune dépendance à Titan (D-003).

## 1. Objectif

Répondre en un écran à : « Combien vaut tout ce que je possède, où est-ce, combien ça m'a rapporté ? »

- Patrimoine global = soldes **réels** des wallets, sans double comptage (D-006).
- Staking : capital, récompenses, APR réel, à partir de l'historique on-chain.
- Hold : prix moyen d'achat, latent, réalisé, historique du PMP.
- Trades Hyperliquid : reconstruits à partir des fills, statistiques nettes de frais et de funding ; trades d'autres plateformes saisis à la main (D-016).
- Évolution du patrimoine et gains par poste dans le temps.

L'outil **ne calcule aucun impôt** (renvoi vers pmpa-crypto) et **ne demande jamais de clé privée** : uniquement des adresses publiques (D-005).

## 2. Installation et lancement (D-002)

```
# Docker (recommandé)
git clone https://github.com/Patart50/wallet-crypto && cd wallet-crypto
mkdir -p data && docker compose up -d     # http://127.0.0.1:8090

# ou Python 3.11+
pip install .
wallet-crypto serve                       # interface, http://127.0.0.1:8090
wallet-crypto serve --demo                # démonstration, données fictives (D-027)
wallet-crypto sync | status | trades      # ligne de commande, cron
```

- Configuration : variables d'environnement ou `.env` (`ALCHEMY_API_KEY`, `WALLET_CRYPTO_PASSWORD`, `WALLET_CRYPTO_DATA`, `WALLET_CRYPTO_TZ`, `WALLET_CRYPTO_SYNC_HOURS`).
- Écoute sur `127.0.0.1` par défaut. Exposition réseau seulement par option explicite, et alors mot de passe obligatoire (D-010, D-021).
- Données dans un seul dossier (`./data` : base SQLite `wallet-crypto.db`, journaux `logs/`). Sauvegarde = copier ce dossier.

## 3. Sources de données (D-004, D-014)

| Réseau | Source | Clé | Contenu |
|---|---|---|---|
| Hyperliquid | API info publique | aucune | compte unifié ou standard, positions, spot, vaults, délégation HYPE, fills, funding, historique de staking |
| EVM (Ethereum, Arbitrum, Base, BSC, Polygon, Optimism) | Alchemy Portfolio API | **Alchemy (celle de l'utilisateur)** | soldes et prix des tokens, spam (sans prix) et poussière (< 1 $) filtrés |
| WCT (Optimism) | RPC Alchemy | Alchemy | lock Stake Weight, récompenses réclamables (appel simulé, rien n'est envoyé), transferts |
| Solana | Alchemy | Alchemy | soldes et prix |
| Bitcoin | mempool.space | aucune | solde d'une adresse (pas de xpub en v1.0) |
| Prix courants | Binance, Hyperliquid, Alchemy | aucune | ordre en D-020 ; taux EUR/USD pour l'affichage (D-015) |
| Prix historiques | Binance, sinon Hyperliquid (bougies journalières) | aucune | cache SQLite, mis à jour pendant la synchronisation (D-022) |

Sans clé Alchemy, l'outil fonctionne pour Hyperliquid et Bitcoin ; EVM et Solana échouent avec un message qui renvoie au guide du README.

Chaque source est une classe enregistrée dans un registre (`sources/base.py`, D-014) : `fetch_balances(adresse)` → lignes d'actifs, positions, lignes à garder en cas de lecture partielle ; `fetch_history(adresse, curseur)` → fills, funding, mouvements de staking depuis ce que la base contient déjà. Client HTTP commun : reprises sur 429 / 5xx, JSON lu en décimal, secrets masqués.

## 4. Synchronisation (D-007)

Code : `sync.py`.

- Automatique selon la fréquence des Réglages (6 h par défaut) tant que le serveur tourne, bouton « Synchroniser », commande `wallet-crypto sync [--if-due]` pour cron.
- Prix historiques mis à jour à la fin de chaque synchronisation (D-022) ; prix courants rafraîchis toutes les 5 min par le serveur (D-024).
- Verrou de fichier (`data/sync.lock`, création atomique, repris s'il a plus de 15 min) : jamais deux synchronisations simultanées.
- Une source en échec n'écrase pas les anciens soldes du wallet ; l'erreur est notée sur le wallet.
- L'échec d'un historique n'annule pas les soldes du même wallet.
- Fills, funding et mouvements de staking archivés localement, import incrémental et idempotent (Hyperliquid ne sert que les 10 000 derniers fills).
- Un snapshot du patrimoine par synchronisation (base des courbes), avec ventilation par wallet et par catégorie.
- Chaque exécution est enregistrée (`sync_run`) ; `--if-due` ne compte que les synchronisations ayant lu au moins un wallet.

## 5. Calculs

Code pur dans `wallet_crypto/core/`, sans réseau ni base, testé. Montants en `Decimal` (D-013). Dates en ms UTC (D-017).

- **Lignes d'actifs** (`assets.py`) : suffixes `_STAKED`, `_PENDING`, `_SPOT`, `HLP_VAULTS` ; catégories liquidités (stablecoins), hold, staking ; une seule fonction de valorisation (`line_value`).
- **Patrimoine** (`portfolio.py`) : somme des lignes réelles ; staking manuel hors wallet ajouté seulement s'il ne double pas un staking suivi automatiquement ; ventilation par poste (staking, hold, trading automatique, trading manuel, autres liquidités, D-011).
- **Staking automatique** (`staking.py`) : capital net = dépôts − retraits ; récompenses re-lockées non comptées comme capital ; APR réel = récompenses ÷ solde moyen pondéré par le temps, annualisé, moyen et 30 jours ; écart entre staké réel et historique signalé.
- **Staking manuel** (`staking.py`) : mode `apr` (montant composé, délai d'un cycle avant de produire, changements de taux) ou `rewards` (récompenses saisies, réintégrées ou en poche), frais sur les gains (D-019).
- **Hold** (`hold.py`) : quantité = wallets ; PMP = fills spot HL (frais déduits) + achats saisis ; dépôts vers le staking sortis au PMP sans résultat ; frais de transfert (quantité sortie, coût conservé) ; historique du PMP ; option « inclure le staké » ; alertes (quantité sans prix d'achat, achats > détenu, ventes > achats).
- **Trades HL** (`trades.py`) : trade = position qui part de 0 et y revient, renforts, réductions, retournements, fills d'un même instant chaînés ; net = PnL prix − frais + funding ; WR, profit factor, espérance, gain et perte moyens ; trades incomplets, liquidés, trous signalés.
- **Trades manuels** (`manual_trades.py`) : levier, marge, latent, ROE, PnL réel saisissable (D-016).
- **Gains par poste** (`gains.py`) : trading automatique et manuel (réalisé + funding), staking (récompenses au cours du moment de réception), hold (réalisé + latent depuis le départ choisi) ; grille journalière dans le fuseau de l'utilisateur.

## 6. Base de données

Code : `db/models.py`, `db/store.py`. SQLite, WAL, clés étrangères actives. Montants en texte décimal (`DecimalText`), détails libres en JSON (`JsonText`).

Tables : `wallet` (avec `auto_trading`, `last_error`), `balance_line`, `hl_position`, `hl_fill`, `hl_funding`, `stake_event`, `snapshot`, `hold_tx`, `manual_stake` (+ `_rate`, `_tx`), `manual_trade` (+ `_tx`), `price_cache`, `kline_cache`, `kv` (version du schéma, paires spot HL, taux EUR, réglages), `sync_run`. Migrations : D-018.

## 7. Ligne de commande

`wallet add RÉSEAUX ADRESSE [--label] [--group] [--no-staking] [--auto-trading]`, `wallet list`, `wallet remove ID`, `sync [--if-due]`, `status [--eur]`, `trades`, `about`, `serve [--host] [--port] [--demo]`. Console sobre (résumé) ; journal détaillé dans `data/logs/wallet-crypto.log`, `-v` pour l'afficher.

## 8. Interface (NiceGUI, sombre par défaut, D-009, D-023)

- **Tableau de bord** : total du patrimoine, évolution depuis le premier relevé, 7 j, 24 h, barre de composition par poste, patrimoine par poste (aire empilée), principaux actifs, gains cumulés par poste depuis un départ au choix ; actifs sans prix et doublons signalés.
- **Wallets** : ajout d'adresses (plusieurs réseaux pour une même adresse 0x, ajout en masse), groupes, case « trading automatique » (D-011), détail des comptes HL et positions ouvertes, dernière sync et erreur.
- **Staking** : cartes automatiques (HYPE, WCT, vaults) puis positions manuelles, doublons signalés et exclus.
- **Hold** : une carte par actif, alertes, saisie d'achats, ventes et frais, historique du PMP.
- **Trades** : statistiques globales, une carte par actif, derniers trades visibles, le reste en tiroir, filtres comptes et période (D-028) ; trades saisis à la main.
- **Graphiques** : un axe, légende, info-bulle avec tous les montants, tableau « Voir les données » sous chacun.
- **Réglages** : clé Alchemy (masquée, guide pas à pas), devise et thème, fréquence de synchronisation, mot de passe (D-021), export et import de la base (D-025).
- **Accès** : écoute sur 127.0.0.1 ; ailleurs, mot de passe obligatoire ; connexion sur `/connexion`.
- **À propos et limites**, auteur et soutien avec QR codes (D-012).

## 9. Jalons

- **J1** ✅ (PR #1) Squelette du paquet, moteur pur réécrit et testé (patrimoine, staking, hold, trades HL et manuels, gains), sources avec tests sur réponses fictives, base SQLite, synchronisation, CLI, CI (ruff, pytest, comparaison des adresses de don).
- **J2** ✅ (PR #2) Interface complète, synchronisation automatique, prix courants et historiques, guide Alchemy dans l'interface, mot de passe, export/import, démonstration, Docker, tests de fumée de l'interface.
- **Corrections d'usage** (D-031, D-032) : nettoyage de l'historique des wallets supprimés, positions ouvertes dans Trades, cases de même hauteur.
- **J3** v1.0 : migrations Alembic, revue de sécurité (D-010, D-021, D-026), vérification sur données réelles, mesure Alchemy, release.

## 10. Hors périmètre v1.0

Clés privées et signature de transactions, xpub Bitcoin, plateformes centralisées par API (architecture prête, D-014 ; prévues après la v1.0, D-033), calcul d'impôt (pmpa-crypto), IA, multi-utilisateurs, application hébergée.
