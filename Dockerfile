FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY docs.json ./


# Functional tests: docker compose run --rm tests
FROM base AS test

COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY pytest.ini ./
COPY tests ./tests

CMD ["pytest"]


# The service (default target)
FROM base AS runtime

# The service does not need root: run it as an unprivileged user.
RUN useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app
USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
