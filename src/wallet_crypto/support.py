"""Auteur et moyens de soutien (wallet D-012).

Copie Python de ``src/support.ts`` de commun-crypto, seule source des adresses (commun D-004).
Ne jamais modifier une adresse ici : la modifier dans commun-crypto, puis recopier. Un test
compare ce fichier à celui de commun-crypto au tag épinglé dans la CI, et vérifie les sommes
de contrôle : une faute de frappe fait échouer la CI.
"""

from __future__ import annotations

from dataclasses import dataclass

from .security import bech32_valid

AUTHOR = {"name": "Arnaud", "handle": "Patart50", "url": "https://github.com/Patart50"}
AUTHOR_DISPLAY = "Arnaud (Patart50)"
SPONSORS_URL = "https://github.com/sponsors/Patart50"
REPO_URL = "https://github.com/Patart50/wallet-crypto"


@dataclass(frozen=True)
class DonationAddress:
    id: str
    label: str
    networks: str
    address: str
    qr: str
    warning: str


DONATION_ADDRESSES: tuple[DonationAddress, ...] = (
    DonationAddress(
        id="btc",
        label="Bitcoin",
        networks="Réseau Bitcoin uniquement (BTC)",
        address="bc1qd5j0yrrxp6wrk5ds0xne97hdrz5fvxjl8q22p4",
        qr="bitcoin:bc1qd5j0yrrxp6wrk5ds0xne97hdrz5fvxjl8q22p4",
        warning="N’envoyez pas de BTC via Lightning ni de BTC « wrappés » sur un autre réseau.",
    ),
    DonationAddress(
        id="evm",
        label="Ethereum et réseaux EVM",
        networks="ETH, USDC… sur Ethereum, Arbitrum, Optimism, Base ou autre réseau compatible EVM",
        address="0x7e4b6bad06813506b724b5ea3cc9545a7b97eba4",
        qr="0x7e4b6bad06813506b724b5ea3cc9545a7b97eba4",
        warning="Adresse 0x uniquement : pas de réseau non EVM (Solana, Tron, Bitcoin…).",
    ),
)


def is_valid_bech32(address: str) -> bool:
    return address.lower().startswith("bc1q") and bech32_valid(address)


def is_valid_evm_address(address: str) -> bool:
    return (
        len(address) == 42
        and address.startswith("0x")
        and all(c in "0123456789abcdefABCDEF" for c in address[2:])
    )
