# Build stage - for compiling dependencies
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libjpeg-dev \
        zlib1g-dev \
        gettext \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
# psycopg2-binary is pinned in requirements.txt -- repeating it here unpinned
# silently overrides that pin. uvicorn is not in requirements.txt, so it stays.
RUN pip install --upgrade "pip>=26.0" \
    && pip install --no-cache-dir -r requirements.txt uvicorn[standard]

# Production stage - minimal runtime image
FROM python:3.13-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Install only runtime dependencies.
#
# `apt-get upgrade` is deliberate: the base image is rebuilt on its own cadence,
# so packages it ships (perl-base, zlib, openssl and friends) can sit on known
# CVEs for as long as the tag goes unrefreshed even though Debian has published
# the fix. Installing named packages alone never touches them. The release
# workflow fails the build on any CRITICAL finding, so a stale base blocks the
# release outright -- 1.15.0 was held back by three fixed perl-base CVEs
# (CVE-2026-13221, CVE-2026-42496, CVE-2026-8376) that this picks up.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        libjpeg62-turbo \
        zlib1g \
        curl \
        netcat-openbsd \
        gettext \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user FIRST
RUN useradd --create-home --uid 1000 appuser

# Copy virtual environment from builder stage WITH correct ownership
COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv

WORKDIR /app

# Copy application code
COPY --chown=appuser:appuser . .

# Copy entrypoint script
COPY --chown=appuser:appuser docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# The COPYs above already set --chown, so only the new dirs need ownership;
# a recursive chown over /app would duplicate a whole layer for no gain.
RUN mkdir -p staticfiles media .secrets \
    && chown appuser:appuser staticfiles media .secrets

USER appuser

# Build metadata. VERSION should match horilla/__version__.py and the release
# tag; the publish workflow passes all three and fails if they disagree.
ARG VERSION=dev
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="Horilla CRM" \
      org.opencontainers.image.description="Free and open source CRM software" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/horilla/horilla-crm" \
      org.opencontainers.image.url="https://www.horilla.com" \
      org.opencontainers.image.documentation="https://docs.horilla.com" \
      org.opencontainers.image.vendor="Horilla" \
      org.opencontainers.image.licenses="LGPL-2.1"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "horilla.asgi:application", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--ws-ping-interval", "20", \
     "--ws-ping-timeout", "20", \
     "--lifespan", "off", \
     "--log-level", "info"]
