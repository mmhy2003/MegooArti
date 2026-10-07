FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.7.13 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    ALEMBIC_CONFIG=/app/src/megooarti/alembic.ini

WORKDIR /app

# Dependencies first, so this layer is reused until the lock file changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY docker-entrypoint.sh ./
RUN uv sync --frozen --no-dev \
    && chmod 0755 docker-entrypoint.sh \
    && useradd --system --uid 10001 --no-create-home megooarti \
    && mkdir -p /var/lib/megooarti \
    && chown megooarti /var/lib/megooarti

VOLUME /var/lib/megooarti

USER megooarti
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "megooarti"]
