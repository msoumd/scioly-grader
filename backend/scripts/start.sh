#!/bin/sh
# Container start: bring the database schema up to date, then serve.
# One web process on purpose: the login rate limiter and the background reading queue
# live in memory, so two processes would double the PIN guesses allowed and could both
# retry the same stuck scan. Reading runs in a thread pool (READER_WORKERS), which is
# where the CPU goes anyway.
set -eu
alembic upgrade head
# The host's HTTPS proxy is the only way in, so trust its X-Forwarded-* headers (real
# client IP for the login limiter, https scheme for HSTS).
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
    --proxy-headers --forwarded-allow-ips="*" --no-server-header
