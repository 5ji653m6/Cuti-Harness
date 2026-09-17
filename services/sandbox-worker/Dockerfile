FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 worker \
    && useradd --uid 10001 --gid worker --no-create-home --shell /usr/sbin/nologin worker

COPY --from=builder /install /usr/local
WORKDIR /service
COPY --chown=worker:worker app ./app

# The worker itself is a high-trust Docker control-plane component. Job containers
# remain separately configured; root is required to access the mounted Docker socket.
USER root
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]

