# syntax=docker/dockerfile:1
FROM python:3.13-slim AS build
WORKDIR /src
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 10001 payplan
WORKDIR /app
COPY --from=build /install /usr/local
COPY alembic.ini ./
COPY alembic ./alembic
USER payplan
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
# Migrations run as a one-off task before each deploy (see .github/workflows/deploy.yml),
# never on container start, so several tasks booting at once can't race on the schema.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
