# Production image for Lens (Fly.io). Tailwind CSS is pre-built & committed
# (static/css/app.css), so no Node is needed in the image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8080

WORKDIR /app

# psycopg[binary] bundles libpq, but build-essential helps any source builds.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Collect static at build time (needs a key; the runtime key comes from secrets).
RUN SECRET_KEY=build-time-only python manage.py collectstatic --noinput

EXPOSE 8080

# Startup script (written with LF here so Windows checkouts can't break it):
# migrate against the mounted volume, seed once if the DB is empty, then serve.
RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -e' \
    'python manage.py migrate --noinput' \
    'if [ "$(python manage.py shell -c "from django.contrib.auth import get_user_model as g; print(g().objects.exists())")" != "True" ]; then' \
    '  echo "Empty database — seeding demo data..."; python manage.py seed_demo || true' \
    'fi' \
    'exec gunicorn config.wsgi:application --bind 0.0.0.0:8080 --workers 2 --timeout 60 --access-logfile - --error-logfile -' \
    > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
