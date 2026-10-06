"""Alchemy : soldes EVM et Solana, staking WCT sur Optimism. Clé de l'utilisateur (D-004).

- **Portfolio API** « Tokens By Wallet » : un appel couvre plusieurs chaînes, prix inclus.
  Chaînes EVM : Ethereum, Arbitrum, Base, BSC, Polygon, Optimism. Un token sans prix est
  presque toujours du spam d'airdrop : ignoré. Poussière (< 1 $) ignorée.
- **WCT (WalletConnect) sur Optimism** : le WCT locké dans le contrat Stake Weight n'est plus
  dans le solde du wallet. ``locks(adresse)`` → ``WCT_STAKED`` ; ``claim(adresse)`` **simulé**
  (``eth_call`` : rien n'est envoyé ni signé) → ``WCT_PENDING`` (réclamable). Historique : les
  transferts WCT wallet → contrat (dépôt), contrat → wallet (retrait), distributeur → wallet
  (récompense).

Adresses des contrats : github.com/WalletConnect/contracts, ``evm/deployments/10.json``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from ..core.assets import AssetLine
from ..money import D
from .base import BalanceResult, HistoryBatch, HistoryCursor, Source, SourceError, add_line, register

log = logging.getLogger("wallet_crypto.sources.alchemy")

PORTFOLIO_URL = "https://api.g.alchemy.com/data/v1/{key}/assets/tokens/by-address"
OP_RPC_URL = "https://opt-mainnet.g.alchemy.com/v2/{key}"
EVM_NETWORKS = ["eth-mainnet", "arb-mainnet", "base-mainnet", "bnb-mainnet", "matic-mainnet", "opt-mainnet"]
SOL_NETWORKS = ["solana-mainnet"]
NET_CHUNK = 5  # nombre de chaînes par appel (limite non documentée : prudence)
MAX_PAGES = 10
NATIVE_SYMBOL = {
    "eth-mainnet": "ETH",
    "arb-mainnet": "ETH",
    "base-mainnet": "ETH",
    "opt-mainnet": "ETH",
    "bnb-mainnet": "BNB",
    "matic-mainnet": "POL",
    "solana-mainnet": "SOL",
}
NATIVE_DECIMALS = {"solana-mainnet": 9}
DUST_USD = Decimal(1)

WCT_TOKEN = "0xeF4461891DfB3AC8572cCf7C794664A8DD927945"
WCT_STAKE_WEIGHT = "0x521B4C065Bbdbe3E20B3727340730936912DfA46"
WCT_REWARD_DISTRIBUTOR = "0xF368F535e329c6d08DFf0d4b2dA961C4e7F3fCAF"
SEL_LOCKS = "0x5de9a137"  # locks(address) → (int128 amount, uint256 end, uint256 transferred)
SEL_CLAIM = "0x1e83409a"  # claim(address) → uint256, simulé avec from = l'utilisateur
WCT_DECIMALS = 18


def raw_to_qty(raw, decimals: int) -> Decimal:
    """Solde brut (hexadécimal, entier ou déjà en unités) → quantité exacte."""
    s = str(raw).strip()
    if s.startswith(("0x", "0X")):
        return Decimal(int(s, 16)).scaleb(-decimals)
    if "." in s:
        return D(s)
    return Decimal(int(s)).scaleb(-decimals)


def parse_token(t: dict) -> tuple[str, Decimal, Decimal | None, str] | None:
    """Token Alchemy → (symbole, quantité, valeur USD ou None, chaîne)."""
    net = t.get("network")
    md = t.get("tokenMetadata") or {}
    is_native = not t.get("tokenAddress")
    sym = md.get("symbol") or (NATIVE_SYMBOL.get(net) if is_native else None)
    dec = md.get("decimals")
    if dec is None and is_native:
        dec = NATIVE_DECIMALS.get(net, 18)
    raw = t.get("tokenBalance")
    if not sym or dec is None or raw is None:
        return None
    try:
        qty = raw_to_qty(raw, int(dec))
    except (ValueError, ArithmeticError):
        return None
    if qty <= 0:
        return None
    price = None
    for p in t.get("tokenPrices") or []:
        if str(p.get("currency", "")).lower() == "usd" and p.get("value") not in (None, ""):
            price = D(p["value"])
            break
    return str(sym).upper(), qty, (qty * price if price is not None else None), net


def enc_address(a: str) -> str:
    return a.lower().removeprefix("0x").rjust(64, "0")


def parse_locks(hexdata: str | None) -> tuple[Decimal, int, Decimal]:
    """Réponse de ``locks(adresse)`` → (WCT locké, fin du lock en s (0 = permanent ou aucun),
    WCT transféré). Le montant est un int128 signé."""
    h = (hexdata or "0x").removeprefix("0x")
    if len(h) < 192:
        return Decimal(0), 0, Decimal(0)
    w = [h[i : i + 64] for i in range(0, 192, 64)]
    amt = int(w[0], 16)
    if amt >= 2**255:
        amt -= 2**256
    return Decimal(amt).scaleb(-WCT_DECIMALS), int(w[1], 16), Decimal(int(w[2], 16)).scaleb(-WCT_DECIMALS)


def iso_ms(ts) -> int:
    try:
        return int(datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return 0


def transfer_qty(t: dict) -> Decimal:
    rc = t.get("rawContract") or {}
    try:
        dec_raw = rc.get("decimal")
        dec = int(dec_raw, 16) if isinstance(dec_raw, str) else int(dec_raw or WCT_DECIMALS)
        return Decimal(int(rc.get("value"), 16)).scaleb(-dec)
    except (TypeError, ValueError):
        return D(t.get("value"))


def parse_wct_transfers(addr: str, transfers: list, kind: str) -> list[dict]:
    out = []
    for t in transfers or []:
        q = transfer_qty(t)
        if q <= 0:
            continue
        uid = t.get("uniqueId") or f"{t.get('hash')}:{kind}"
        out.append(
            {
                "source": "WCT_OP",
                "address": addr,
                "asset": "WCT",
                "time_ms": iso_ms((t.get("metadata") or {}).get("blockTimestamp")),
                "kind": kind,
                "qty": q,
                "hash": t.get("hash"),
                "ext_id": f"wct:{uid}"[:190],
                "detail": None,
            }
        )
    return out


class _AlchemyBase(Source):
    needs_alchemy = True
    networks: list[str] = []

    def tokens(self, address: str) -> tuple[dict[str, AssetLine], dict[str, int]]:
        url = PORTFOLIO_URL.format(key=self.alchemy_key)
        lines: dict[str, AssetLine] = {}
        skipped = {"no_price": 0, "dust": 0}
        for i in range(0, len(self.networks), NET_CHUNK):
            chunk = self.networks[i : i + NET_CHUNK]
            page_key = None
            for _ in range(MAX_PAGES):
                body = {
                    "addresses": [{"address": address, "networks": chunk}],
                    "withMetadata": True,
                    "withPrices": True,
                    "includeNativeTokens": True,
                    "includeErc20Tokens": True,
                }
                if page_key:
                    body["pageKey"] = page_key
                try:
                    j = self.http.post_json(url, body, timeout=30)
                except Exception as exc:
                    raise SourceError(f"Alchemy : {exc}") from exc
                data = j.get("data") or {}
                err = j.get("error")
                if isinstance(err, dict) and err.get("partialErrors"):
                    log.warning("Alchemy, erreurs partielles : %s", err["partialErrors"])
                for t in data.get("tokens") or []:
                    parsed = parse_token(t)
                    if not parsed:
                        continue
                    sym, qty, val, net = parsed
                    if val is None:
                        skipped["no_price"] += 1
                        continue
                    if val < DUST_USD:
                        skipped["dust"] += 1
                        continue
                    add_line(lines, sym, qty, val, "alchemy", chain=net)
                page_key = data.get("pageKey")
                if not page_key:
                    break
        return lines, skipped

    def fetch_balances(self, address: str, track_staking: bool = True) -> BalanceResult:
        lines, skipped = self.tokens(address.strip())
        warnings = []
        if skipped["no_price"]:
            warnings.append(f"{skipped['no_price']} token(s) sans prix ignoré(s) (spam d'airdrop probable)")
        return BalanceResult(lines, warnings=warnings)


@register
class EvmSource(_AlchemyBase):
    network = "EVM"
    label = "EVM (Alchemy)"
    networks = EVM_NETWORKS

    def rpc(self, method: str, params: list):
        try:
            j = self.http.post_json(
                OP_RPC_URL.format(key=self.alchemy_key),
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=30,
            )
        except Exception as exc:
            raise SourceError(f"Alchemy RPC Optimism {method} : {exc}") from exc
        if j.get("error"):
            raise SourceError(f"Alchemy RPC Optimism {method} : {j['error']}")
        return j.get("result")

    def wct_stake(self, address: str) -> dict[str, AssetLine]:
        res = self.rpc(
            "eth_call", [{"to": WCT_STAKE_WEIGHT, "data": SEL_LOCKS + enc_address(address)}, "latest"]
        )
        amount, end, transferred = parse_locks(res)
        pending: Decimal | None = None
        try:
            res2 = self.rpc(
                "eth_call",
                [
                    {"from": address, "to": WCT_REWARD_DISTRIBUTOR, "data": SEL_CLAIM + enc_address(address)},
                    "latest",
                ],
            )
            pending = Decimal(int(res2, 16)).scaleb(-WCT_DECIMALS) if res2 and res2 != "0x" else Decimal(0)
        except SourceError as exc:
            log.warning("WCT, réclamable inconnu : %s", exc)
        out: dict[str, AssetLine] = {}
        if amount > 0:
            out["WCT_STAKED"] = AssetLine(
                "WCT_STAKED",
                amount,
                None,
                "wct_lock",
                extra={"lock_end": end, "permanent": end == 0, "transferred": transferred},
            )
        if pending and pending > 0:
            out["WCT_PENDING"] = AssetLine("WCT_PENDING", pending, None, "wct_claimable")
        return out

    def fetch_balances(self, address: str, track_staking: bool = True) -> BalanceResult:
        result = super().fetch_balances(address, track_staking)
        if track_staking:
            try:
                result.lines.update(self.wct_stake(address.strip()))
            except SourceError as exc:
                # lock illisible : les autres soldes sont bons, on garde l'ancien WCT staké
                result.keep_previous = ("WCT_STAKED", "WCT_PENDING")
                result.warnings.append(f"Staking WCT illisible, ancienne valeur gardée : {exc}")
        return result

    def transfers(self, from_addr: str | None = None, to_addr: str | None = None) -> list[dict]:
        out: list[dict] = []
        page_key = None
        for _ in range(20):
            p = {
                "fromBlock": "0x0",
                "toBlock": "latest",
                "category": ["erc20"],
                "contractAddresses": [WCT_TOKEN],
                "withMetadata": True,
                "excludeZeroValue": True,
                "maxCount": "0x3e8",
                "order": "asc",
            }
            if from_addr:
                p["fromAddress"] = from_addr
            if to_addr:
                p["toAddress"] = to_addr
            if page_key:
                p["pageKey"] = page_key
            res = self.rpc("alchemy_getAssetTransfers", [p]) or {}
            out.extend(res.get("transfers") or [])
            page_key = res.get("pageKey")
            if not page_key:
                break
        return out

    def fetch_history(self, address: str, track_staking: bool, cursor: HistoryCursor) -> HistoryBatch:
        if not track_staking:
            return HistoryBatch()
        addr = address.strip()
        rows = parse_wct_transfers(addr, self.transfers(from_addr=addr, to_addr=WCT_STAKE_WEIGHT), "DEPOSIT")
        if rows or "WCT_OP" in cursor.known_sources:
            rows += parse_wct_transfers(
                addr, self.transfers(from_addr=WCT_STAKE_WEIGHT, to_addr=addr), "WITHDRAW"
            )
            rows += parse_wct_transfers(
                addr, self.transfers(from_addr=WCT_REWARD_DISTRIBUTOR, to_addr=addr), "REWARD"
            )
        return HistoryBatch(stake_events=rows)


@register
class SolanaSource(_AlchemyBase):
    network = "SOL"
    label = "Solana (Alchemy)"
    networks = SOL_NETWORKS
