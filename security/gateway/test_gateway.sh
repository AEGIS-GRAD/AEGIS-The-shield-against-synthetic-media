#!/bin/bash
URL="http://localhost:8081/api/video"

echo "========================================"
echo "Testing AEGIS API Gateway"
echo "========================================"

echo -e "\n[Test 1] Missing API Key (Attacker Simulation)"
echo "Expected: 401"
STATUS1=$(curl -s -o /dev/null -w "%{http_code}" -X POST $URL)
echo "Status Code: $STATUS1"
if [ "$STATUS1" -eq 401 ]; then
    echo -e "\033[0;32mPASS: Gateway successfully blocked the request.\033[0m"
else
    echo -e "\033[0;31mFAIL\033[0m"
fi

# Try to extract key from .env
KEY="your_secure_token_here"
if [ -f "../../.env" ]; then
    ENV_KEY=$(grep "^INTERNAL_API_KEY=" ../../.env | cut -d '=' -f2)
    if [ ! -z "$ENV_KEY" ]; then
        KEY=$(echo $ENV_KEY | tr -d '\r')
    fi
fi

echo -e "\n[Test 2] Valid API Key (System Simulation)"
echo "Expected: 502 (AI containers not running)"
STATUS2=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "X-Internal-Token: $KEY" $URL)
echo "Status Code: $STATUS2"
if [ "$STATUS2" -eq 502 ]; then
    echo -e "\033[0;32mPASS: Gateway accepted key and attempted route.\033[0m"
else
    echo -e "\033[0;31mFAIL\033[0m"
fi

echo -e "\nTests complete."
