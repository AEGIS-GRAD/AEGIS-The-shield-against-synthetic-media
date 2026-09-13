#!/bin/bash
# End-to-end smoke tests against a running `docker compose up` stack.
# For the authoritative, CI-run automated suite (no live containers needed),
# see validator/tests/ - this script is for a human to sanity-check the real
# nginx -> gateway_validator -> detector pipeline locally.
URL="http://localhost:8081/api/video"

PASS_COLOR='\033[0;32m'
FAIL_COLOR='\033[0;31m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0

check_status() {
    local test_name="$1"
    local expected="$2"
    local actual="$3"
    echo "Status Code: $actual (expected $expected)"
    if [ "$actual" -eq "$expected" ]; then
        echo -e "${PASS_COLOR}PASS: $test_name${NC}"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "${FAIL_COLOR}FAIL: $test_name${NC}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

echo "========================================"
echo "Testing AEGIS API Gateway"
echo "========================================"

echo -e "\n[Test 1] Missing API Key (Attacker Simulation)"
STATUS1=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL")
check_status "Gateway blocked the unauthenticated request." 401 "$STATUS1"

# Try to extract key from .env
KEY="your_secure_token_here"
if [ -f "../../.env" ]; then
    ENV_KEY=$(grep "^INTERNAL_API_KEY=" ../../.env | cut -d '=' -f2)
    if [ ! -z "$ENV_KEY" ]; then
        KEY=$(echo $ENV_KEY | tr -d '\r')
    fi
fi

echo -e "\n[Test 2] Valid Key, Oversized Upload (>50MB Attacker Simulation)"
TMP_BIG=$(mktemp)
head -c $((50 * 1024 * 1024 + 1)) /dev/zero > "$TMP_BIG"
STATUS2=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "X-Internal-Token: $KEY" \
    -F "file=@$TMP_BIG;filename=clip.mp4;type=video/mp4" \
    "$URL")
rm -f "$TMP_BIG"
check_status "Gateway rejected an oversized upload before it reached the validator." 413 "$STATUS2"

echo -e "\n[Test 3] Valid Key, Spoofed File (Plain Text Renamed to .mp4)"
TMP_SPOOF=$(mktemp)
printf 'this is definitely not a video file' > "$TMP_SPOOF"
STATUS3=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "X-Internal-Token: $KEY" \
    -F "file=@$TMP_SPOOF;filename=clip.mp4;type=video/mp4" \
    "$URL")
rm -f "$TMP_SPOOF"
check_status "Validator rejected a text file spoofed as .mp4 via magic bytes." 415 "$STATUS3"

echo -e "\n[Test 4] Valid Key, Path-Traversal Filename"
TMP_TRAV=$(mktemp)
printf 'irrelevant content' > "$TMP_TRAV"
STATUS4=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "X-Internal-Token: $KEY" \
    -F "file=@$TMP_TRAV;filename=../../etc/passwd.mp4;type=video/mp4" \
    "$URL")
rm -f "$TMP_TRAV"
check_status "Validator rejected a path-traversal filename." 400 "$STATUS4"

echo -e "\n========================================"
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "========================================"
[ "$FAIL_COUNT" -eq 0 ]
