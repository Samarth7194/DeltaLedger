FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential curl \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN python -m pip install --upgrade pip \
  && python -m pip install -e .

# Run as an unprivileged user; /app is chowned after the editable install so the
# egg-info written by `pip install -e .` stays readable/writable for it.
RUN useradd --system --create-home --uid 10001 app \
  && chown -R app:app /app
USER app

EXPOSE 8000

# Liveness only (/health is cheap and does not touch dependencies). Use /ready for
# dependency checks. The port is fixed because the CMD below binds 8000.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
