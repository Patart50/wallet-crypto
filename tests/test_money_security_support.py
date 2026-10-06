import os
import re
from decimal import Decimal
from pathlib import Path

import pytest

from wallet_crypto.money import D, D_opt, dumps, loads, round_to, to_str
from wallet_crypto.security import (
    InputRejected,
    bech32_valid,
    looks_like_secret,
    mask_secret,
    normalize_address,
)
from wallet_crypto.support import DONATION_ADDRESSES, is_valid_bech32, is_valid_evm_address

# ---------------------------------------------------------------- money


def test_decimal_exact_where_float_is_not():
    assert 0.1 + 0.2 != 0.3
    assert D("0.1") + D("0.2") == D("0.3")
    assert D(0.1) == Decimal("0.1")  # float converti par sa représentation courte


def test_loads_reads_decimals():
    data = loads('{"px": 0.1, "sz": "2", "n": 3}')
    assert isinstance(data["px"], Decimal) and data["px"] == Decimal("0.1")
    assert data["n"] == 3


def test_to_str_and_dumps():
    assert to_str(D("1.2300")) == "1.23"
    assert to_str(D("1E+3")) == "1000"
    assert to_str(D(0)) == "0"
    assert dumps({"a": D("0.10")}) == '{"a":"0.1"}'


def test_D_variants():
    assert D(None) == 0 and D("") == 0 and D(" 1 000 ") == 1000
    assert D_opt("") is None and D_opt(None) is None
    with pytest.raises(ValueError):
        D("abc")
    with pytest.raises(TypeError):
        D(True)
    assert round_to(D("2.345")) == D("2.35")


# ---------------------------------------------------------------- sécurité (D-005)

SECRETS = [
    "0x" + "ab" * 32,  # clé privée EVM
    "ab" * 32,
    " ".join(["abandon"] * 11 + ["about"]),  # phrase de 12 mots
    " ".join(["legal"] * 24),
    "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ",  # WIF d'exemple (documentation Bitcoin)
    "4" + "z" * 87,  # format d'une clé Solana (88 caractères base58)
]


@pytest.mark.parametrize("secret", SECRETS)
def test_secrets_are_refused(secret):
    assert looks_like_secret(secret)
    for net in ("HL", "EVM", "SOL", "BTC"):
        with pytest.raises(InputRejected, match="clé privée"):
            normalize_address(net, secret)


def test_valid_addresses():
    assert normalize_address("EVM", "0xABCDEF0123456789abcdef0123456789ABCDEF01") == (
        "0xabcdef0123456789abcdef0123456789abcdef01"
    )
    assert normalize_address("hl", "HL:0x1111111111111111111111111111111111111111").startswith("0x1111")
    assert normalize_address("BTC", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")
    assert normalize_address("BTC", "1BoatSLRHtKNngkdXEeobR76b53LETtpyT")
    assert normalize_address("SOL", "So1aNaTestAddre55111111111111111111111111")


@pytest.mark.parametrize(
    "net,addr",
    [
        ("EVM", "0x123"),
        ("BTC", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdx"),  # checksum faux
        (
            "BTC",
            "xpub6CUGRUonZSQ4TWtTMmzXdrXDtypWKiKrhko4egpiMZbpiaQL2jkwSB1icqYh2cfDfVxdx4df189oLKnC5fSwqPfgyP3hooxujYzAu3fDVmz",
        ),
        ("SOL", "abc"),
        ("TRON", "T123"),
    ],
)
def test_invalid_addresses(net, addr):
    with pytest.raises(InputRejected):
        normalize_address(net, addr)


def test_mask_secret():
    assert mask_secret("abcdefghijklmnop") == "abcd…mnop"
    assert mask_secret("") == ""
    assert "…" in mask_secret("short")


# ---------------------------------------------------------------- soutien (D-012)


def test_donation_checksums():
    btc = next(a for a in DONATION_ADDRESSES if a.id == "btc")
    evm = next(a for a in DONATION_ADDRESSES if a.id == "evm")
    assert is_valid_bech32(btc.address) and bech32_valid(btc.address)
    assert btc.qr == f"bitcoin:{btc.address}"
    assert is_valid_evm_address(evm.address)
    assert evm.qr == evm.address


def test_typo_breaks_checksum():
    btc = DONATION_ADDRESSES[0].address
    typo = btc[:-1] + ("q" if btc[-1] != "q" else "p")
    assert not bech32_valid(typo)


def test_addresses_match_commun_crypto():
    """La CI fournit le support.ts de commun-crypto au tag épinglé (wallet D-012)."""
    path = os.environ.get("COMMUN_CRYPTO_SUPPORT")
    if not path:
        pytest.skip("COMMUN_CRYPTO_SUPPORT absent (vérifié en CI)")
    ts = Path(path).read_text(encoding="utf-8")
    ts_addresses = re.findall(r"address:\s*'([^']+)'", ts)
    assert sorted(ts_addresses) == sorted(a.address for a in DONATION_ADDRESSES)
    for a in DONATION_ADDRESSES:
        assert f"qr: '{a.qr}'" in ts
