# syntax=docker/dockerfile:1
#
# chesssnake api-endpoint image.
#
# Build context is the repository root, not this directory:
#   docker build -f docker/build/Dockerfile -t chesssnake .
#
# The image carries chesssnake with every optional dependency — the api extra
# (FastAPI, uvicorn, pydantic, SQLAlchemy), the postgres extra (psycopg2), and
# the client extra (requests) — so one image serves both the SQLite and the
# PostgreSQL compose stacks, and can also act as a client for smoke tests. The
# backend is chosen at runtime by CHESSSNAKE__DATABASE__URL, not at build time.

ARG PYTHON_VERSION=3.12


# --- build ------------------------------------------------------------------
# Dependencies are installed into a self-contained virtualenv that the runtime
# stage copies wholesale, so pip, its cache, and the source tree never reach the
# final image.
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /src

# Only what the build backend actually reads. Copying the whole repo here would
# bust the layer cache on every unrelated change.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# Every runtime dependency publishes manylinux wheels (pillow, psycopg2-binary),
# so no compiler or -dev headers are needed.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install ".[api,client,postgres]"


# --- runtime ----------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="chesssnake" \
      org.opencontainers.image.description="chesssnake api-endpoint: play, render, and persist chess games over REST" \
      org.opencontainers.image.source="https://github.com/GabeBecker2048/chesssnake" \
      org.opencontainers.image.licenses="MIT"

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv

# Run as a non-root user. /data is created here rather than by the compose file
# so that a fresh named volume mounted over it inherits this ownership — Docker
# seeds an empty volume from the image path, permissions included. Without it a
# SQLite database under /data would be unwritable.
RUN useradd --create-home --uid 10001 chesssnake \
    && mkdir -p /data \
    && chown chesssnake:chesssnake /data

USER chesssnake
WORKDIR /home/chesssnake
VOLUME ["/data"]
EXPOSE 8000

# Uses the packaged client rather than curl, which slim images do not ship.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

ENTRYPOINT ["chesssnake"]
# 0.0.0.0 rather than the 127.0.0.1 default: inside a container, binding to
# loopback would make the published port unreachable.
CMD ["api-endpoint", "--host", "0.0.0.0", "--port", "8000"]
