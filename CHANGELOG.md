# Journal des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions selon [SemVer](https://semver.org/lang/fr/).

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
