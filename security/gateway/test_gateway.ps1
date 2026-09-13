# End-to-end smoke tests against a running `docker compose up` stack.
# For the authoritative, CI-run automated suite (no live containers needed),
# see validator/tests/ - this script is for a human to sanity-check the real
# nginx -> gateway_validator -> detector pipeline locally.
$url = "http://localhost:8081/api/video"
$passCount = 0
$failCount = 0

function Check-Status($testName, $expected, $actual) {
    Write-Host "Status Code: $actual (expected $expected)"
    if ($actual -eq "$expected") {
        Write-Host "PASS: $testName" -ForegroundColor Green
        $script:passCount++
    } else {
        Write-Host "FAIL: $testName" -ForegroundColor Red
        $script:failCount++
    }
}

Write-Host "========================================"
Write-Host "Testing AEGIS API Gateway"
Write-Host "========================================"

Write-Host "`n[Test 1] Missing API Key (Attacker Simulation)"
$status1 = curl.exe -s -o NUL -w "%{http_code}" -X POST $url
Check-Status "Gateway blocked the unauthenticated request." 401 $status1

# Try to read the actual key from the .env file
$envFile = "../../.env"
$key = "your_secure_token_here"
if (Test-Path $envFile) {
    $match = Select-String -Path $envFile -Pattern "^INTERNAL_API_KEY=(.*)$"
    if ($match) {
        $key = $match.Matches.Groups[1].Value.Trim()
    }
}

Write-Host "`n[Test 2] Valid Key, Oversized Upload (>50MB Attacker Simulation)"
$tmpBig = New-TemporaryFile
$stream = [System.IO.File]::OpenWrite($tmpBig.FullName)
$stream.SetLength(50MB + 1)
$stream.Close()
$bigPath = "$($tmpBig.FullName);filename=clip.mp4;type=video/mp4"
$status2 = curl.exe -s -o NUL -w "%{http_code}" -X POST -H "X-Internal-Token: $key" -F "file=@$bigPath" $url
Remove-Item $tmpBig.FullName -Force
Check-Status "Gateway rejected an oversized upload before it reached the validator." 413 $status2

Write-Host "`n[Test 3] Valid Key, Spoofed File (Plain Text Renamed to .mp4)"
$tmpSpoof = New-TemporaryFile
Set-Content -Path $tmpSpoof.FullName -Value "this is definitely not a video file" -NoNewline
$spoofPath = "$($tmpSpoof.FullName);filename=clip.mp4;type=video/mp4"
$status3 = curl.exe -s -o NUL -w "%{http_code}" -X POST -H "X-Internal-Token: $key" -F "file=@$spoofPath" $url
Remove-Item $tmpSpoof.FullName -Force
Check-Status "Validator rejected a text file spoofed as .mp4 via magic bytes." 415 $status3

Write-Host "`n[Test 4] Valid Key, Path-Traversal Filename"
$tmpTrav = New-TemporaryFile
Set-Content -Path $tmpTrav.FullName -Value "irrelevant content" -NoNewline
$travPath = "$($tmpTrav.FullName);filename=../../etc/passwd.mp4;type=video/mp4"
$status4 = curl.exe -s -o NUL -w "%{http_code}" -X POST -H "X-Internal-Token: $key" -F "file=@$travPath" $url
Remove-Item $tmpTrav.FullName -Force
Check-Status "Validator rejected a path-traversal filename." 400 $status4

Write-Host "`n========================================"
Write-Host "Results: $passCount passed, $failCount failed"
Write-Host "========================================"
