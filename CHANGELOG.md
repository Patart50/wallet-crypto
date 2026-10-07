# Journal des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions selon [SemVer](https://semver.org/lang/fr/).

## Non publié

### Modifié
- Supprimer un wallet retire aussi sa part des relevés passés et son historique importé ; bouton « Nettoyer l'historique » dans les Réglages pour les wallets déjà supprimés (copie de sauvegarde avant nettoyage).
- Les positions ouvertes Hyperliquid passent de Wallets en haut de l'écran Trades.
- Les cases de chiffres d'une même ligne ont toutes la même hauteur.

## 0.2.0 — J2 : interface web, Docker

### Ajouté
- Interface web en français (`wallet-crypto serve`, http://127.0.0.1:8090) : tableau de bord (patrimoine, évolution, composition, gains cumulés par poste), Wallets, Staking, Hold, Trades, Réglages, À propos et limites. Thème sombre et clair, mobile, navigation au clavier.
- Saisies dans l'interface : adresses (en masse, plusieurs réseaux), achats, ventes et frais du hold, positions de staking manuelles (dépôts, retraits, récompenses, changements de taux), trades d'autres plateformes.
- Synchronisation automatique selon une fréquence réglable, bouton « Synchroniser », prix courants rafraîchis toutes les 5 minutes.
- Prix historiques journaliers (Binance, sinon Hyperliquid) mis en cache pendant la synchronisation, pour valoriser récompenses et hold dans le temps.
- Clé Alchemy saisissable dans les Réglages, avec guide pas à pas ; la variable d'environnement reste prioritaire.
- Mot de passe de l'interface, obligatoire hors de la machine locale.
- Export et import de la base.
- Démonstration avec données fictives : `wallet-crypto serve --demo`.
- Image Docker non root et `docker-compose.yml` publié sur 127.0.0.1 seulement.
- Auteur et soutien avec QR codes générés localement.

### Modifié
- L'écran Trades montre tous les comptes Hyperliquid par défaut.

## 0.1.0 — J1 : moteur, sources, base, ligne de commande

### Ajouté
- Moteur de calcul pur, en décimal exact, testé : patrimoine sans double comptage, staking automatique (APR réel, récompenses re-lockées) et manuel (APR composé ou récompenses saisies), hold (prix moyen, frais de transfert, passages vers le staking), trades Hyperliquid (reconstruction à partir des fills, statistiques nettes), trades saisis à la main, gains cumulés par poste.
- Sources : Hyperliquid (compte unifié ou standard, positions, spot, vaults, délégation HYPE, fills, funding, historique de staking), Alchemy (EVM sur 6 chaînes, Solana, staking WCT sur Optimism), mempool.space (Bitcoin), prix Binance. Registre extensible pour de futures plateformes.
- Base SQLite locale (montants stockés en texte décimal exact), archivage incrémental et idempotent des historiques.
- Synchronisation avec verrou de fichier : une source en échec garde ses anciens soldes ; un relevé du patrimoine par synchronisation.
- Ligne de commande : `wallet add | list | remove`, `sync [--if-due]`, `status [--eur]`, `trades`, `about`.
- Refus des clés privées et phrases de récupération ; contrôle des adresses par réseau ; clé Alchemy masquée dans les journaux et les messages.
- Auteur et soutien, adresses de don vérifiées en CI et comparées à commun-crypto.

### Corrigé par rapport au module d'origine
- Staking manuel en mode « récompenses » non réintégrées : les récompenses étaient comptées deux fois dans la quantité détenue.
