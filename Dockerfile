FROM python:3.11-slim

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY requirements.txt .
# requirements.txt is the dev/test set. Production additionally reads keys from
# Google Secret Manager (key_manager._load_from_secret_manager), so its client
# lib is installed here in the image only — not carried in local dev installs.
RUN pip install --no-cache-dir -r requirements.txt google-cloud-secret-manager==2.29.0

# Production code only — storelink.py is the local mock API used in dev/tests
# and keys.json never ships in the image (prod reads from Secret Manager).
COPY key_manager.py observability.py server.py storelink_client.py ./

ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    PORT=8080

EXPOSE 8080

RUN mkdir -p /app/logs && chown -R app:app /app
USER app

CMD ["python", "server.py"]
