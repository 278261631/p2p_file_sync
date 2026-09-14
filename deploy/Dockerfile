FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY server ./server

RUN [ -f server/accounts.json ] || cp server/accounts.example.json server/accounts.json
RUN pip install --no-cache-dir ".[server]"

EXPOSE 18765
# Terminate TLS at a reverse proxy and forward X-Forwarded-Proto.  Plaintext
# ws:// is rejected unless PFS_ALLOW_INSECURE=1 is set (never in production).
# Set FORWARDED_ALLOW_IPS to the proxy's address so its headers are trusted.
CMD ["uvicorn", "server.signal_server:app", "--host", "0.0.0.0", "--port", "18765", "--proxy-headers"]
