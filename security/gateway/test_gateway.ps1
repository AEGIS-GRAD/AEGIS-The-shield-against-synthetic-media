$url = "http://localhost:8081/api/video"

Write-Host "========================================"
Write-Host "Testing AEGIS API Gateway"
Write-Host "========================================"

Write-Host "`n[Test 1] Missing API Key (Attacker Simulation)"
Write-Host "Expected: 401 Unauthorized"
$status1 = curl.exe -s -o NUL -w "%{http_code}" -X POST $url
Write-Host "Status Code: $status1"
if ($status1 -eq "401") { 
    Write-Host "PASS: Gateway successfully blocked the request." -ForegroundColor Green 
} else { 
    Write-Host "FAIL" -ForegroundColor Red 
}

# Try to read the actual key from the .env file
$envFile = "../../.env"
$key = "your_secure_token_here"
if (Test-Path $envFile) {
    $match = Select-String -Path $envFile -Pattern "^INTERNAL_API_KEY=(.*)$"
    if ($match) {
        $key = $match.Matches.Groups[1].Value.Trim()
    }
}

Write-Host "`n[Test 2] Valid API Key (System Simulation)"
Write-Host "Expected: 502 Bad Gateway (AI containers are not running yet)"
$status2 = curl.exe -s -o NUL -w "%{http_code}" -X POST -H "X-Internal-Token: $key" $url
Write-Host "Status Code: $status2"
if ($status2 -eq "502") { 
    Write-Host "PASS: Gateway accepted the key and attempted to route traffic." -ForegroundColor Green 
} else { 
    Write-Host "FAIL" -ForegroundColor Red 
}

Write-Host "`nTests complete."
