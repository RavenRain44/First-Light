FROM node:24-bookworm-slim AS dashboard
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=build_ca,target=/tmp/build-ca.pem \
    if [ -f /tmp/build-ca.pem ]; then export NODE_EXTRA_CA_CERTS=/tmp/build-ca.pem; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN --mount=type=secret,id=build_ca,target=/tmp/build-ca.pem \
    if [ -f /tmp/build-ca.pem ]; then export PIP_CERT=/tmp/build-ca.pem; fi; \
    pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=dashboard /build/dist /app/frontend/dist
# Populate the seven historical events without inference or network access.
RUN DEMO_MODE=true MODEL_PROVIDER=none python -c "import asyncio; from pathlib import Path; from scripts import build_history; build_history.OUT = Path('var/history'); asyncio.run(build_history.main())"
RUN groupadd --gid 10001 closurecall && useradd --uid 10001 --gid closurecall --no-create-home closurecall && chown -R closurecall:closurecall /app
USER closurecall
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
