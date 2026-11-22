#!/bin/sh
# Restore an encrypted backup into a database (replaces the app's tables there).
#   RESTORE_DATABASE_URL=postgresql://... BACKUP_PASSPHRASE=... sh scripts/restore.sh in.dump.gpg
# Restore into a NEW Supabase project or a scratch database first and check it; only
# then point the app at it (or restore over production during a planned stop).
set -eu
in="${1:?usage: restore.sh INPUT.dump.gpg}"
: "${RESTORE_DATABASE_URL:?set RESTORE_DATABASE_URL}" "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE}"
url=$(printf '%s' "$RESTORE_DATABASE_URL" | sed 's#^postgresql+psycopg://#postgresql://#')
gpg --batch --quiet --decrypt --pinentry-mode loopback --passphrase-fd 3 "$in" 3<<PASS \
  | pg_restore --dbname="$url" --clean --if-exists --no-owner --no-privileges --exit-on-error
$BACKUP_PASSPHRASE
PASS
echo "restored $in"
