FROM node:22-alpine AS ui
WORKDIR /src/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
RUN addgroup --system firstlight && adduser --system --ingroup firstlight firstlight
COPY pyproject.toml README.md requirements.lock ./
COPY backend/ ./backend/
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1 && \
    python -m pip install --no-cache-dir --constraint requirements.lock .
COPY --from=ui /src/ui/dist ./ui/dist
COPY scripts/ ./scripts/
RUN mkdir -p /app/data/evidence /app/data/exports && chown -R firstlight:firstlight /app
USER firstlight
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["uvicorn", "backend.app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
