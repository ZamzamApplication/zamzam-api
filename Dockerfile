FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system zamzam \
    && useradd --system --gid zamzam --home-dir /app zamzam

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY app/ ./app/
COPY docker-entrypoint.sh /usr/local/bin/zamzam-entrypoint
RUN chmod 0755 /usr/local/bin/zamzam-entrypoint \
    && chown -R zamzam:zamzam /app

EXPOSE 8080

ENTRYPOINT ["zamzam-entrypoint"]
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8080"]
