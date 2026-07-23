#!/usr/bin/env bash
# Publish THIS machine's real trade journal into the repo, so every other
# machine — and a Claude session working on the repo — can fold it into
# training (prepare.py picks up journals/*.jsonl automatically).
#
#   bash sync_journal.sh              # publishes as journals/<hostname>.jsonl
#   bash sync_journal.sh vps-media    # explicit machine name
#
# The journal holds only trade results (symbol, P&L, entry features): no
# keys, no tokens. Secrets (lumuria.env, keypairs) are blocked by .gitignore
# and must never be committed. Pushing requires this machine to have write
# access to the repo (fine-grained token or deploy key).
set -euo pipefail
cd "$(dirname "$0")"

NAME="${1:-$(hostname -s)}"
JOURNAL="${JOURNAL:-lumuria_trades.jsonl}"

if [ ! -s "$JOURNAL" ]; then
  echo "nothing to sync: $JOURNAL is missing or empty"
  exit 0
fi

mkdir -p journals
cp "$JOURNAL" "journals/$NAME.jsonl"
git add "journals/$NAME.jsonl"
if git diff --cached --quiet; then
  echo "journals/$NAME.jsonl already up to date"
  exit 0
fi
trades=$(wc -l < "journals/$NAME.jsonl" | tr -d ' ')
git commit -m "journal: $NAME — $trades closed trades"
git push
echo "published journals/$NAME.jsonl ($trades trades)"
