# ============================================================
# Stage 1: Build dependencies in a separate layer
# ============================================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# Install build-time system dependencies for compiled packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================================
# Stage 2: Final slim runtime image
# ============================================================
FROM python:3.12-slim-bookworm AS runtime

# Install only runtime system dependencies (Chromium for Selenium)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    xvfb \
    libxi6 \
    libgconf-2-4 \
    libnss3 \
    libxkbcommon-x11-0 \
    libxrandr2 \
    libgtk-3-0 \
    libasound2 \
    libpq5 \
    chromium \
    chromium-driver \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user for security (with a writable home for Chrome profile data)
RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -m -s /sbin/nologin appuser

# Set environment variables for Chromium (Debian installs as 'chromium', not 'google-chrome')
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

# Copy application code
COPY --chown=appuser:appuser . .

# Create writable directories for the non-root user
RUN mkdir -p /app/trained_models /tmp/chrome-profile /tmp/chrome-crashes \
    && chown -R appuser:appuser /app/trained_models /tmp/chrome-profile /tmp/chrome-crashes

# Switch to non-root user
USER appuser

# Expose the port FastAPI app will run on
EXPOSE 9000

# Health check for container orchestration (ECS/Docker Compose)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:9000/api/docs || exit 1

# Run FastAPI with optimized settings
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1", "--loop", "uvloop", "--http", "httptools"]
