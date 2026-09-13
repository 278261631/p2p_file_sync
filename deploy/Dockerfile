FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY server ./server

RUN [ -f server/accounts.json ] || cp server/accounts.example.json server/accounts.json
RUN pip install --no-cache-dir ".[server]"

EXPOSE 8765
CMD ["uvicorn", "server.signal_server:app", "--host", "0.0.0.0", "--port", "8765"]
