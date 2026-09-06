# Cybersecurity API Gateway

This folder contains the configuration and testing scripts for the **Nginx API Gateway**.

## What is this?
The API Gateway acts as a "Security Bouncer" for all incoming traffic before it reaches the backend AI detector microservices.

Instead of writing a custom Python application to validate tokens, we use a highly performant **Nginx Reverse Proxy**.

## Features
1. **Authentication:** It intercepts all requests and enforces the `X-Internal-Token` header. If the key is missing or invalid, it instantly drops the request with a `401 Unauthorized`.
2. **Audit Logging:** It acts as a security camera, logging every single request across the Docker network (Timestamp, Source IP, Endpoint, and Status Code) to standard output.
3. **Routing:** If authentication passes, it routes the traffic securely to the appropriate internal AI container.

## How it works
The `nginx.conf.template` file contains the logic.
When you run `docker-compose up`, Docker automatically uses the `envsubst` feature to read the `INTERNAL_API_KEY` from your root `.env` file and securely injects it into Nginx without hardcoding any secrets.

## How to Test
We have provided automated test scripts that mimic both an attacker and a valid system to verify the Gateway's behavior.

Run the appropriate script for your OS from within this directory:

**Windows:**
```powershell
.\test_gateway.ps1
```

**Linux/Mac:**
```bash
./test_gateway.sh
```

**Expected Results:**
- **Test 1 (No Key):** Returns `401 Unauthorized` (Gateway blocked it).
- **Test 2 (Valid Key):** Returns `502 Bad Gateway` (Gateway allowed it, but the AI containers haven't been implemented yet, which is correct).
