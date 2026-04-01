#!/bin/sh
# Fix ownership of data directory (may be a volume mount owned by root)
chown -R aeye:aeye /app/data 2>/dev/null || true
exec gosu aeye "$@"
