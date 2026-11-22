#!/bin/sh
# Dump the app's tables (public schema) and encrypt the dump with a passphrase.
#   BACKUP_DATABASE_URL=postgresql://... BACKUP_PASSPHRASE=... sh scripts/backup.sh out.dump.gpg
# Needs pg_dump (same or newer major version than the server) and gpg.
# Use Supabase's *session* pooler or direct connection (port 5432): pg_dump does not work
# through the transaction pooler (6543).
set -eu
out="${1:?usage: backup.sh OUTPUT.dump.gpg}"
: "${BACKUP_DATABASE_URL:?set BACKUP_DATABASE_URL}" "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE}"
url=$(printf '%s' "$BACKUP_DATABASE_URL" | sed 's#^postgresql+psycopg://#postgresql://#')
pg_dump "$url" --schema=public --format=custom --no-owner --no-privileges \
  | gpg --batch --yes --symmetric --cipher-algo AES256 --pinentry-mode loopback \
        --passphrase-fd 3 --output "$out" 3<<PASS
$BACKUP_PASSPHRASE
PASS
echo "backup written to $out ($(wc -c < "$out") bytes)"
