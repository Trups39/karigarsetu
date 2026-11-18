# KarigarSetu app image: FastAPI backend + the website it serves.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/karigarsetu

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY frontend frontend
COPY backend/app backend/app
COPY backend/db backend/db

# Run as a normal user, not root.
RUN useradd --create-home --uid 1000 karigarsetu && chown -R karigarsetu /srv/karigarsetu
USER karigarsetu
WORKDIR /srv/karigarsetu/backend

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# --proxy-headers: behind Caddy, use the visitor's real IP (login lockout and contact-form limits need it).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
