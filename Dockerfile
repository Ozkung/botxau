# Backtesting/tooling image only - NOT for live trading.
#
# The live engine (scripts/run_live.py) needs the MetaTrader5 package, which
# has no Linux build and talks to a running MT5 *desktop terminal* over IPC,
# not a network API. There is no way to run it in a container. This image
# is for everything that doesn't touch MT5: the backtester, the preflight
# check's config/environment checks, and the test suite. See docker-compose.yml.
FROM python:3.11-slim

WORKDIR /app

# Layer this separately so `docker compose build` doesn't reinstall
# dependencies every time application code changes.
COPY requirements.txt .
# The MetaTrader5 line in requirements.txt is marked `; platform_system ==
# "Windows"`, so pip skips it here automatically - no Windows-only package
# ever gets installed into this Linux image.
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ bot/
COPY scripts/ scripts/
COPY installer/configure.py installer/configure.py
COPY config.example.yaml .
COPY tests/ tests/
COPY docs/ docs/

# data/, results/, logs/ and config.yaml are bind-mounted by docker-compose.yml
# so backtest output and any config you write land on the host, not inside
# a container that gets thrown away.
RUN mkdir -p data results logs

CMD ["python", "scripts/doctor.py", "--config", "config.yaml", "--skip-mt5"]
