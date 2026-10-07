"""Fumée de l'interface : le vrai serveur, en démonstration (données fictives, aucun appel
réseau). Chaque page est construite côté serveur avant la réponse : une exception dans un
écran donne une erreur 500 ici."""

import os
import socket
import subprocess
import sys
import time

import pytest
import requests

PAGES = {
    "/": "Patrimoine global",
    "/wallets": "Ajouter des adresses",
    "/staking": "Positions saisies",
    "/hold": "Prix moyen",
    "/trades": "Trades sur d'autres plateformes",
    "/reglages": "Clé Alchemy",
    "/a-propos": "Auteur et soutien",
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(tmp_path, *args, env_extra=None):
    port = free_port()
    env = {**os.environ, "WALLET_CRYPTO_DATA": str(tmp_path / "data"), **(env_extra or {})}
    env.pop("ALCHEMY_API_KEY", None)
    env.pop("PYTEST_CURRENT_TEST", None)  # sinon NiceGUI se croit dans ses propres tests
    proc = subprocess.Popen(
        [sys.executable, "-m", "wallet_crypto", "serve", "--demo", "--port", str(port), *args],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            requests.get(base + "/a-propos", timeout=2, allow_redirects=False)
            return proc, base
        except requests.ConnectionError:
            if proc.poll() is not None:
                break
            time.sleep(0.5)
    proc.kill()
    raise AssertionError(f"serveur non démarré : {proc.stdout.read() if proc.stdout else ''}")


def stop(proc):
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    proc, base = start(tmp_path_factory.mktemp("ui"))
    yield base
    stop(proc)


@pytest.mark.parametrize("path,text", PAGES.items())
def test_pages_render(server, path, text):
    r = requests.get(server + path, timeout=30)
    assert r.status_code == 200
    assert text in r.text
    assert "Arnaud (Patart50)" in r.text  # pied de page sur chaque écran


def test_assets_are_local(server):
    r = requests.get(server + "/", timeout=30)
    for cdn in ("cdn.jsdelivr", "unpkg.com", "googleapis", "cdnjs"):
        assert cdn not in r.text
    assert (
        requests.get(server + "/wc-static/fonts/public-sans-latin-wght-normal.woff2", timeout=10).status_code
        == 200
    )


def test_password_protects_pages(tmp_path):
    proc, base = start(tmp_path, env_extra={"WALLET_CRYPTO_PASSWORD": "motdepasse-test"})
    try:
        r = requests.get(base + "/hold", timeout=30, allow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/connexion?suite=/hold"
        r = requests.get(base + "/connexion", timeout=30)
        assert r.status_code == 200 and "Mot de passe" in r.text and "Patrimoine global" not in r.text
    finally:
        stop(proc)


def test_refuses_network_without_password(tmp_path):
    env = {**os.environ, "WALLET_CRYPTO_DATA": str(tmp_path / "data")}
    env.pop("WALLET_CRYPTO_PASSWORD", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    r = subprocess.run(
        [sys.executable, "-m", "wallet_crypto", "serve", "--host", "0.0.0.0", "--port", str(free_port())],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode != 0
    assert "sans mot de passe" in r.stderr + r.stdout


def test_foreign_host_refused_without_password(server):
    # « DNS rebinding » : une page web fait pointer son nom vers 127.0.0.1 (D-035)
    r = requests.get(server + "/", headers={"Host": "attaquant.example:8090"}, timeout=30)
    assert r.status_code == 403 and "Patrimoine" not in r.text
    port = server.rsplit(":", 1)[1]
    assert requests.get(server + "/", headers={"Host": f"localhost:{port}"}, timeout=30).status_code == 200


def test_foreign_host_allowed_with_password(tmp_path):
    proc, base = start(tmp_path, env_extra={"WALLET_CRYPTO_PASSWORD": "motdepasse-test"})
    try:
        r = requests.get(base + "/", headers={"Host": "wallet.lan"}, timeout=30, allow_redirects=False)
        assert r.status_code == 303  # vers la connexion
    finally:
        stop(proc)
