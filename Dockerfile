# wallet-crypto : image d'exécution (wallet D-010, D-026)
# - utilisateur non root, données dans le volume /data
# - le conteneur écoute sur 0.0.0.0 ; docker-compose.yml ne publie le port que sur 127.0.0.1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WALLET_CRYPTO_DATA=/data

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . \
    && useradd --create-home --uid 10001 wallet \
    && mkdir -p /data \
    && chown wallet:wallet /data

USER wallet
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8090

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/a-propos', timeout=4)" || exit 1

CMD ["wallet-crypto", "serve", "--host", "0.0.0.0", "--port", "8090", "--docker"]
