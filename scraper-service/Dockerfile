FROM python:3.12-slim-bookworm

# Install Chromium + driver for Selenium. `tzdata` is required so that
# Chrome's ICU timezone database can resolve "UTC" reliably — without it,
# `Emulation.setTimezoneOverride` silently falls back to the host tz and
# times scraped from FlashScore end up offset by whatever tz the VM
# happens to be in (europe-west9 → CEST/UTC+2).
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    curl \
    tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Pin the whole container — and every child process, including Chrome —
# to UTC. This is the primary timezone guarantee; the scraper also
# applies a CDP override at runtime as defense in depth.
ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/UTC /etc/localtime && echo "UTC" > /etc/timezone

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY . /app

ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

EXPOSE 9001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9001", "--workers", "1"]
