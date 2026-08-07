# Base minima + SOLO Chromium. La imagen oficial de Playwright traeria ademas
# Firefox y WebKit, que este monitor no usa y pesan de mas en la descarga.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=America/Lima

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /root/.cache

COPY checker.py run_local.sh ./

CMD ["bash", "./run_local.sh"]
