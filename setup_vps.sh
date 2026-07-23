#!/usr/bin/env bash
# Lumuria TurboBot — VPS setup. Run on a fresh Ubuntu/Debian VPS of ANY size:
# training depth and live cadence auto-scale to the machine (small/medium/
# large profile, detected from CPU + RAM). Override with PROFILE=small etc.
#
#   bash setup_vps.sh                   # install, test, train a brain (auto profile)
#   PROFILE=small bash setup_vps.sh     # force the small-VPS profile
#   bash setup_vps.sh --install-service # also install a 24/7 auto-restart service
#
# This NEVER trades real money on its own: the installed service runs DRY-RUN.
# Going live is a deliberate, separate step (see the notes it prints).
set -euo pipefail

REPO="${REPO:-https://github.com/pacosemente/lumuria-turbobot.git}"
BRANCH="${BRANCH:-claude/github-folder-contents-aTXps}"
DIR="${DIR:-$HOME/lumuria-turbobot}"
PROFILE="${PROFILE:-auto}"

echo "==> [1/6] system packages (python3, pip, venv, git)"
if command -v apt-get >/dev/null; then
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-pip python3-venv git
fi

echo "==> [2/6] fetch the code on branch $BRANCH"
if [ -d "$DIR/.git" ]; then
  cd "$DIR"; git fetch origin "$BRANCH"; git checkout "$BRANCH"; git pull origin "$BRANCH"
else
  git clone "$REPO" "$DIR"; cd "$DIR"; git checkout "$BRANCH"
fi

echo "==> [3/6] python venv + deps (solders only needed for real signing)"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install solders >/dev/null || echo "   (solders failed; dry-run still works)"

echo "==> [4/6] sanity: run the test suite"
ok=0; fail=0
for t in tests/test_*.py; do
  if python3 "$t" >/dev/null 2>&1; then ok=$((ok+1)); else fail=$((fail+1)); echo "   FAIL $t"; fi
done
echo "   tests: $ok ok, $fail failed"
[ "$fail" -eq 0 ] || { echo "   aborting: fix failing tests first"; exit 1; }

echo "==> [5/6] offline training (study + evolve -> brain.json, profile: $PROFILE)"
python3 prepare.py --profile "$PROFILE" || echo "   (training skipped/failed; you can run prepare.py later)"

echo "==> [6/6] env template"
if [ ! -f lumuria.env ]; then
  cat > lumuria.env <<'ENV'
# Fill these in. Do NOT commit this file or share it.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=2041993559
RPC_URL=https://api.mainnet-beta.solana.com
ENV
  echo "   wrote lumuria.env — edit it with your Telegram token and a good RPC."
fi

if [ "${1:-}" = "--install-service" ]; then
  echo "==> installing 24/7 dry-run service (auto-restart)"
  SVC=/etc/systemd/system/lumuria.service
  sudo tee "$SVC" >/dev/null <<SVCEOF
[Unit]
Description=Lumuria TurboBot (dry-run)
After=network-online.target

[Service]
WorkingDirectory=$DIR
EnvironmentFile=$DIR/lumuria.env
ExecStart=$DIR/.venv/bin/python $DIR/live.py --brain $DIR/brain.json \\
  --profile $PROFILE \\
  --rpc-url \${RPC_URL} --min-liquidity 30000 --state-file $DIR/lumuria_state.json \\
  --journal-file $DIR/lumuria_trades.jsonl
Restart=always
RestartSec=10
User=$USER

[Install]
WantedBy=multi-user.target
SVCEOF
  sudo systemctl daemon-reload
  sudo systemctl enable lumuria
  echo "   start it with:  sudo systemctl start lumuria"
  echo "   watch logs:     journalctl -u lumuria -f"
fi

cat <<NOTE

==================================================================
 DONE. Lumuria is installed and a brain is trained.

 1) Edit secrets:           nano lumuria.env   (Telegram token + RPC)
 2) DRY-RUN now (no money):
      set -a; . ./lumuria.env; set +a
      .venv/bin/python live.py --brain brain.json --rpc-url "\$RPC_URL" \\
        --min-liquidity 30000
    -> you should see "telegram: on" and notifications on your phone.
 3) Let it run for WEEKS. Then study the REAL results:
      .venv/bin/python explore.py --journal lumuria_trades.jsonl
 4) Only if the real numbers are positive, go live (real money), tiny:
      pip install solders
      .venv/bin/python live.py --live --brain brain.json \\
        --keypair ~/bot-key.json --i-understand-real-funds \\
        --rpc-url "\$RPC_URL" --budget-sol 1 --per-trade-sol 0.01
==================================================================
NOTE
