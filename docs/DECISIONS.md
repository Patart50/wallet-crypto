# Journal des décisions — wallet-crypto

Chaque décision est numérotée et ne se réécrit pas : on en ajoute une nouvelle qui remplace l'ancienne. Statut : ✅ actée · ⚠️ à vérifier · 🔁 remplacée. Dans les échanges entre projets, préfixer : « wallet D-003 ».

## D-001 ✅ Nom, dépôt, licence
`wallet-crypto`, dépôt `Patart50/wallet-crypto`, AGPL-3.0 (choix d'Arnaud, 6 oct. 2026). Remplace la « version connectée en Python » envisagée dans PROGRAMME. Le fichier GPL-3.0 créé par GitHub a été remplacé par l'AGPL-3.0.

## D-002 ✅ Python auto-hébergé, pour utilisateurs avertis
Choix d'Arnaud (6 oct. 2026) : application Python que l'utilisateur fait tourner chez lui (Docker ou `pip install`), pas un site statique. Avantages : synchronisation en tâche de fond, archivage complet de l'historique, aucune contrainte CORS. Les versions navigateur de suivi de trades et de staking existent par ailleurs pour le grand public. Écart assumé avec le principe « 100 % client-side » du programme : les autres principes restent (local, aucune télémétrie, français, sombre/clair, aucune donnée réelle dans le dépôt).

## D-003 ✅ Réécriture sans dépendance à Titan
Le module wallet de Titan (wallet_models, wallet_sync, wallet_ui, wallet_charts) sert de référence pour les calculs, mais aucun fichier n'est repris tel quel : il dépend de Redis, de la base de klines, de Postgres et du bot. Retirés : snapshot et setups IA, liaison au bot, liquidations, ancien solde USDC calculé. Les calculs repris sont réécrits en fonctions pures avec tests. Validé par Arnaud (6 oct. 2026) ; les trades saisis à la main restent finalement (D-016).

## D-004 ⚠️ Sources : chaque utilisateur sa clé Alchemy
Seule clé nécessaire : Alchemy (gratuite), fournie par l'utilisateur dans `.env` ou dans Réglages, jamais dans le dépôt. Hyperliquid, mempool.space et Binance (prix) sont publics. Prix : Alchemy pour EVM et Solana, `allMids` HL, sinon cours Binance ; bougies Binance mises en cache dans SQLite pour valoriser les récompenses et le hold dans le temps (remplace la table de klines de Titan). Quota gratuit d'Alchemy à vérifier sur une sync réelle avant la v1.0.

## D-005 ✅ Lecture seule, adresses publiques uniquement
L'outil ne demande, ne stocke et n'accepte jamais de clé privée, de phrase de récupération ni de clé API de plateforme avec droits de retrait. Un champ qui ressemble à une clé privée (64 caractères hexadécimaux, 12 ou 24 mots) est refusé avec un message.

## D-006 ✅ Patrimoine sans double comptage
Reprend la règle V3.4 du module Titan : le total est la somme des lignes réelles des wallets ; Hold et Staking sont des vues de ces lignes, jamais ajoutées en plus. Un staking manuel sur un actif déjà suivi automatiquement est exclu et signalé.

## D-007 ✅ Synchronisation
Toutes les 6 h dans le serveur, bouton manuel, commande `wallet-crypto sync` pour cron ; verrou de fichier dans le dossier de données (remplace le verrou Redis). Source en échec : anciens soldes conservés. Un snapshot par sync.

## D-008 🔁 Montants en Decimal, stockés en texte (remplacée par D-013)
Comme le principe programme (decimal.js) : calculs en `decimal.Decimal`, stockage en chaînes décimales dans SQLite (le type Numeric de SQLite arrondit en flottant). Les réponses d'API sont lues en `Decimal` dès le parsing (`json.loads(..., parse_float=Decimal)`). À trancher : graphiques en float à l'affichage seulement.

## D-009 ✅ Interface NiceGUI, SQLite, SQLAlchemy
NiceGUI (déjà maîtrisé, ECharts intégré, rendu soigné en sombre) ; SQLite via SQLAlchemy 2 (un fichier, rien à installer) ; migrations Alembic dès la v1.0 pour que les mises à jour ne cassent pas la base (calendrier : D-018). Thème sombre par défaut, clair disponible. Interface en français. Accessibilité : contraste vérifié, navigation au clavier testée ; pas d'audit axe-core complet promis (composants Quasar). Validé par Arnaud (6 oct. 2026).

## D-010 ✅ Sécurité réseau
Écoute sur 127.0.0.1 par défaut. `--host 0.0.0.0` exige un mot de passe (haché, session signée) et affiche un avertissement : la page révèle tout le patrimoine. Clé Alchemy jamais affichée en clair ni écrite dans les journaux (masquée dans les logs de débogage). Conteneur Docker non root. Validé par Arnaud (6 oct. 2026) ; masquage fait en J1, serveur et Docker en J2 (D-021, D-026).

## D-011 ✅ Trading automatique ou manuel : étiquette explicite
Remplace la détection par le nom du compte (« maître », « bot », « titan ») : chaque compte HL porte une case « trading automatique ». Sert à séparer les deux postes dans les graphiques et les gains.

## D-012 ✅ Auteur et soutien en Python
Mêmes règles que le programme : « Créé par Arnaud (Patart50) · Soutenir le projet », sans nom de famille, Sponsors et deux adresses de don, QR codes générés localement (`segno`, J2), `.github/FUNDING.yml`. La source unique reste `commun-crypto/src/support.ts` (commun D-004) ; Python ne pouvant l'importer, `wallet_crypto/support.py` en est une copie, avec un test de checksum (bech32, EVM) et un test qui compare les adresses à celles de commun-crypto au tag épinglé dans la CI (`COMMUN_CRYPTO_TAG`, v1.2.0). Validé par Arnaud (6 oct. 2026).

## D-013 ⚠️ Décimal exact plutôt que flottant
Remplace D-008, contenu identique : `Decimal` à 50 chiffres partout (calculs, parsing JSON avec `parse_float=Decimal`, stockage texte via `DecimalText`), `float` seulement pour dessiner les graphiques. Arnaud a demandé de garder `float`, « plus précis pour les vrais traders » (6 oct. 2026) : c'est l'inverse. Un `float` binaire arrondit dès la saisie (0,1 + 0,2 = 0,30000000000000004) et ces écarts s'accumulent sur des milliers de fills ; `Decimal` reproduit au chiffre près les montants des API (qui sont des chaînes) et des relevés de plateformes. Le seul avantage du `float` est la vitesse, sans effet à cette échelle (des dizaines de milliers de fills se rejouent en moins d'une seconde). À confirmer par Arnaud ; revenir au `float` resterait possible, mais toucherait tout le moteur.

## D-014 ✅ Sources extensibles : un registre
Demande d'Arnaud : prévoir le branchement d'autres plateformes. Chaque source est une classe (`sources/base.py`) qui renvoie des soldes (`BalanceResult`) et, si elle le peut, un historique (`HistoryBatch` : fills, funding, mouvements de staking), sans toucher à la base. Elle se déclare avec `@register` pour un code réseau. L'orchestrateur stocke ce qu'elle renvoie ; patrimoine, hold et staking n'ont rien à changer. Une lecture partielle peut demander de garder d'anciennes lignes (`keep_previous`, cas du lock WCT illisible). Futures sources envisagées : plateformes centralisées en lecture seule (clé API sans droit de retrait, D-005).

## D-015 ✅ Devise d'affichage : dollar par défaut, euro en option
Validé par Arnaud. Les montants restent calculés et stockés en USD (les API parlent en dollars ; USDT et USDC assimilés). L'affichage en euros convertit au cours `EURUSDT` de Binance, enregistré à chaque synchronisation (`kv: eur_per_usd`). Sans cours connu, l'affichage reste en dollars plutôt que d'afficher une valeur fausse.

## D-016 ✅ Trades saisis à la main conservés
Choix d'Arnaud (6 oct. 2026), précise D-003 : les trades d'autres plateformes saisis à la main restent dans l'outil « pour le moment », en attendant leurs connecteurs (D-014). Levier au niveau de la position, PnL réel saisissable (remplace le PnL calculé). Ne pas y ressaisir les trades Hyperliquid, importés automatiquement. Tables `manual_trade` et `manual_trade_tx`, calcul `core/manual_trades.py` ; écran au J2.

## D-017 ✅ Dates en millisecondes UTC, calendrier dans le fuseau de l'utilisateur
Toutes les dates stockées sont des entiers en ms UTC (le module d'origine mélangeait des dates locales naïves et des ms). Le calendrier des récompenses de staking manuel (minuit, jour de la semaine, du mois) et la grille journalière des graphiques se calculent dans le fuseau configuré (`WALLET_CRYPTO_TZ`, Europe/Paris par défaut).

## D-018 ✅ Schéma : création automatique jusqu'à la v1.0, Alembic avant publication
Tant qu'aucune version n'est publiée, `create_all` crée les tables manquantes et la version du schéma est notée (`kv: schema_version`). Les migrations Alembic sont mises en place au J3, avant la v1.0 : c'est à partir de là que des utilisateurs auront des bases à faire évoluer.

## D-019 ✅ Correctif : staking manuel en mode « récompenses »
Dans le module d'origine, une position manuelle dont les récompenses ne sont pas réintégrées comptait ces récompenses deux fois dans la quantité détenue (montant net + poche). Ici : montant = capital net, poche = gain net de frais, quantité détenue = montant + poche. Vérifié par test.

## D-020 ✅ Prix courants pendant une synchronisation
Ordre : stablecoin = 1 ; Binance (`XUSDT`, `XUSDC`, `XFDUSD`, `XBTC × BTCUSDT`) ; prix médian Hyperliquid (perp, puis paire spot) ; prix déduit d'une ligne Alchemy du même token. Le prix trouvé est noté sur la ligne (`px_sync`) et dans un cache par actif, chemin compris. Valorisation d'une ligne : valeur fournie par la source > stablecoin > prix courant > prix de la synchronisation > cache ; sans prix, la ligne est signalée et non comptée.

## D-021 ✅ Mot de passe de l'interface
Haché avec scrypt (bibliothèque standard, sel aléatoire, comparaison en temps constant), 8 caractères minimum. Deux sources : variable `WALLET_CRYPTO_PASSWORD` (prioritaire, hachée au démarrage) ou écran Réglages. Sessions signées par un secret aléatoire gardé dans `data/secret.key` (droits 600). Pages protégées par une redirection HTTP 303 vers `/connexion` ; un échec de connexion attend une seconde. `serve --host` hors boucle locale sans mot de passe : refus de démarrer (sauf `--docker`, D-026).

## D-022 ✅ Prix historiques : clôtures journalières en cache, mises à jour pendant la synchronisation
Pour valoriser les récompenses au jour de réception et le hold jour par jour (graphique des gains). Table `kline_cache` (symbole, jour UTC, clôture). Source par actif : Binance `XUSDT` puis `XUSDC`, sinon bougies Hyperliquid (`candleSnapshot`, utile pour HYPE). Seuls les actifs utiles sont chargés (achats, ventes, récompenses), à partir de leur premier mouvement, de façon incrémentale. L'interface lit le cache et n'appelle jamais le réseau pour cela. Au-delà de trois jours sans cours : pas de prix plutôt qu'un prix périmé ; l'actif est exclu du hold du graphique et signalé. Remplace un premier essai qui téléchargeait depuis l'interface.

## D-023 ✅ Identité visuelle et graphiques
Identité du programme (commun-crypto `theme.css`) : papier et encre marine, accent bleu, Public Sans pour l'interface, Source Serif 4 pour le montant du patrimoine, chiffres tabulaires. Polices embarquées (`ui/static/fonts`, licence OFL), aucune ressource externe (vérifié : zéro requête hors du serveur). Sombre par défaut, clair disponible. Séries des graphiques : 5 couleurs fixes par poste, validées par le validateur de palette sur chaque surface (ΔE daltonisme ≥ 8,4 entre voisins ; en clair, 3 séries sous 3:1, d'où valeurs écrites à côté et tableau « Voir les données » sous chaque graphique). Pas d'anneau de répartition (5 parts non séparables entre toutes les paires) : une barre de composition sous le total.

## D-024 ✅ Prix courants rafraîchis par le serveur
Toutes les 5 minutes tant que l'interface tourne (Binance, puis Hyperliquid) : seuls des noms de paires sont envoyés. Ils valorisent l'écran entre deux synchronisations ; au-delà de 30 minutes sans rafraîchissement, retour aux prix de la dernière synchronisation. Désactivé en démonstration.

## D-025 ✅ Export et import de la base
Export : copie cohérente par l'API de sauvegarde de SQLite, même pendant une synchronisation. Import : vérifie que le fichier est une base wallet-crypto d'une version prise en charge, garde la base actuelle dans `data/backups/`, puis la remplace.

## D-026 ✅ Docker
Image `python:3.12-slim`, utilisateur non root, données dans le volume `/data`, vérification de santé. `docker-compose.yml` : port publié sur 127.0.0.1 seulement, racine en lecture seule, aucune capacité, `no-new-privileges`, utilisateur = propriétaire du dossier `./data` de l'hôte. Dans le conteneur, le serveur écoute sur 0.0.0.0 avec `--docker` (option cachée) : autorisé sans mot de passe parce que compose ne publie que sur la boucle locale ; avertissement dans le journal. La CI construit l'image et la lance dans ces conditions.

## D-027 ✅ Démonstration
`wallet-crypto serve --demo` : base entièrement fictive (graine fixe) dans un dossier séparé `data-demo/`, 90 jours de relevés, trades, staking, saisies, prix historiques fictifs. Aucune API contactée, synchronisation désactivée. Sert aux captures du README et aux tests de l'interface.

## D-028 ✅ Trades : tous les comptes par défaut
L'écran Trades affiche par défaut tous les comptes Hyperliquid ; un filtre par compte et par période permet d'isoler le trading automatique ou manuel (D-011).
