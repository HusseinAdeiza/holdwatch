#!/usr/bin/env bash
# verify_all.sh — end-to-end verification of everything a judge can touch.
# Nothing here trusts a previous result; every claim is re-tested live.
set -uo pipefail

DASH=https://holdwatch-dashboard.onrender.com
RECV=https://holdwatch-receiver.onrender.com
REPO=https://raw.githubusercontent.com/HusseinAdeiza/holdwatch/main
VIDEO=https://www.youtube.com/watch?v=bFOglGDKJpM
PAGE=https://devpost.com/software/holdwatch-paypal-payout-holds-explained
PASS=0; FAIL=0

ok(){ printf "  \033[32mPASS\033[0m  %s\n" "$1"; PASS=$((PASS+1)); }
no(){ printf "  \033[31mFAIL\033[0m  %s\n" "$1"; FAIL=$((FAIL+1)); }
chk(){ if [ "$2" = "$3" ]; then ok "$1 ($2)"; else no "$1 — got '$2', want '$3'"; fi; }

echo "── 1. live services ──────────────────────────────────"
chk "dashboard /api/health" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 90 $DASH/api/health)" "200"
chk "receiver  /health"     "$(curl -s -o /dev/null -w '%{http_code}' --max-time 90 $RECV/health)" "200"

echo
echo "── 2. the product a judge sees ───────────────────────"
EV=$(curl -s --max-time 120 "$DASH/api/events?ai=0")
T=$(echo "$EV" | python3 -c "import sys,json;print(json.load(sys.stdin)['total'])")
V=$(echo "$EV" | python3 -c "import sys,json;print(json.load(sys.stdin)['verified'])")
C=$(echo "$EV" | python3 -c "import sys,json;print(json.load(sys.stdin)['covered'])")
R=$(echo "$EV" | python3 -c "import sys,json;print(json.load(sys.stdin)['review']['passed'])")
P=$(echo "$EV" | python3 -c "import sys,json;print(any(e['facts'].get('amount')=='USD 4,200.00' for e in json.load(sys.stdin)['events']))")
J=$(echo "$EV" | python3 -c "import sys,json;print(any(e['facts'].get('payer')=='John Doe' for e in json.load(sys.stdin)['events']))")
chk "events"          "$T" "7"
chk "verified"        "$V" "7"
chk "types covered"   "$C" "19"
chk "outside reviewer" "$R" "True"
chk "\$4,200 card present" "$P" "True"
chk "payer John Doe"      "$J" "True"

echo
echo "── 3. AI layer ───────────────────────────────────────"
# Written to a file first: piping straight into python failed when the response
# arrived slowly, and the traceback masked the real result. Verified separately —
# all 7 cards DO have AI text.
curl -s --max-time 150 "$DASH/api/events" -o /tmp/verify_ai.json
AI=$(python3 -c "
import json
d=json.load(open('/tmp/verify_ai.json'))
print(sum(1 for e in d['events'] if (e.get('ai') or {}).get('text')))" 2>/dev/null)
chk "cards with AI text" "$AI" "7"
AIERR=$(python3 -c "
import json
d=json.load(open('/tmp/verify_ai.json'))
print(d['ai_stats'].get('errors',-1))" 2>/dev/null)
chk "AI errors (cache now persists)" "$AIERR" "0"

echo
echo "── 4. security: forgeries rejected ────────────────────"
# Two paths: a bare POST (no signature headers at all) and one that presents
# forged signature headers. Both must be rejected, and neither may be stored.
code=$(curl -s -o /tmp/v1 -w '%{http_code}' --max-time 90 -X POST $RECV/ \
  -H "Content-Type: application/json" \
  -d '{"id":"VERIFY-BARE","event_type":"PAYMENT.PAYOUTS-ITEM.HELD"}')
chk "bare POST rejected" "$code" "400"
code=$(curl -s -o /tmp/v2 -w '%{http_code}' --max-time 90 -X POST $RECV/ \
  -H "Content-Type: application/json" \
  -H "PAYPAL-TRANSMISSION-ID: v1" -H "PAYPAL-TRANSMISSION-TIME: 2026-01-01T00:00:00Z" \
  -H "PAYPAL-TRANSMISSION-SIG: 111" -H "PAYPAL-AUTH-ALGO: SHA256withRSA" \
  -H "PAYPAL-CERT-URL: https://api.paypal.com/f.pem" \
  -d '{"id":"VERIFY-SIG","event_type":"PAYMENT.PAYOUTS-ITEM.HELD"}')
chk "forged w/ sig headers" "$code" "400"
ST=$(curl -s --max-time 60 $RECV/events | python3 -c "import sys,json;print(json.load(sys.stdin)['unique'])")
chk "events stored (must be 0)" "$ST" "0"

# The VPS receiver is the one with a webhook_id configured, so it verifies for
# real and rejects on PayPal's answer rather than on missing config.
vcode=$(curl -s -o /tmp/v3 -w '%{http_code}' --max-time 90 -X POST http://127.0.0.1:8099/ \
  -H "Content-Type: application/json" \
  -H "PAYPAL-TRANSMISSION-ID: v1" -H "PAYPAL-TRANSMISSION-TIME: 2026-01-01T00:00:00Z" \
  -H "PAYPAL-TRANSMISSION-SIG: 111" -H "PAYPAL-AUTH-ALGO: SHA256withRSA" \
  -H "PAYPAL-CERT-URL: https://api.paypal.com/f.pem" \
  -d '{"id":"VERIFY-VPS","event_type":"PAYMENT.PAYOUTS-ITEM.HELD"}')
chk "VPS receiver (verified path)" "$vcode" "400"

echo
echo "── 5. PayPal registration ─────────────────────────────"
cd /root/web3alphatester/paypal
REG=$(python3 register_webhook.py --list 2>/dev/null | grep -c "^  [0-9A-Z]*  ->")
URLR=$(python3 register_webhook.py --list 2>/dev/null | grep -oE 'https://[^ ]+' | head -1)
chk "exactly one subscription" "$REG" "1"
chk "points at" "$URLR" "$RECV"

echo
echo "── 6. submission artefacts ────────────────────────────"
chk "repo"          "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 https://github.com/HusseinAdeiza/holdwatch)" "200"
chk "README"        "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 $REPO/README.md)" "200"
chk "LICENSE (MIT)" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 $REPO/LICENSE)" "200"
chk "DEPLOY.md"     "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 $REPO/DEPLOY.md)" "200"
chk "video"         "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 $VIDEO)" "200"
chk "devpost page"  "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 $PAGE)" "200"

echo
echo "── 7. offline reproducibility ─────────────────────────"
python3 scenarios.py --run > /tmp/ev.txt 2>&1
# Parse with python, not grep. The output pads with spaces before the colon —
# "precision (clean)   : 1.0" — and two grep patterns were wrong because of it,
# reporting false failures against correct values.
read -r R P F <<<"$(python3 - <<'PY'
import re
t = open('/tmp/ev.txt').read()
def grab(label):
    m = re.search(re.escape(label) + r'\s*:\s*([0-9.]+)', t)
    return m.group(1) if m else ''
print(grab('recall (hold shapes)'), grab('precision (clean)'), grab('F1'))
PY
)"
chk "eval recall"    "$R" "0.8"
chk "eval precision" "$P" "1.0"
chk "eval f1"        "$F" "0.889"
python3 hold_signals.py --self-test >/dev/null 2>&1 && ok "rule engine self-test" || no "rule engine self-test"
python3 explainer.py fixtures/sample_payout_held.json >/dev/null 2>&1 && ok "explains fixture offline" || no "explains fixture offline"

echo
echo "── 8. VPS services ───────────────────────────────────"
for s in holdwatch-receiver holdwatch-dashboard holdwatch-tunnel render-keepalive.timer; do
  chk "$s" "$(systemctl is-active $s)" "active"
done

echo
echo "════════════════════════════════════════════════════"
printf "  %d passed, %d failed\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && echo "  ALL GREEN" || echo "  FAILURES ABOVE"
