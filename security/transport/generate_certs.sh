#!/bin/bash
mkdir -p certs
cd certs

echo "1. Generating Root CA..."
openssl req -x509 -newkey rsa:4096 -days 365 -nodes -keyout ca.key -out ca.crt -subj "/C=EG/ST=Cairo/L=Cairo/O=AEGIS/OU=Security/CN=AEGIS Root CA"

echo "2. Generating Server Certificate (Ingestion Node)..."
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/C=EG/ST=Cairo/L=Cairo/O=AEGIS/OU=Ingestion/CN=localhost"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365

echo "3. Generating Client Certificate (Edge Camera)..."
openssl req -newkey rsa:2048 -nodes -keyout client.key -out client.csr -subj "/C=EG/ST=Cairo/L=Cairo/O=AEGIS/OU=EdgeDevices/CN=camera-001"
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365

echo "Certificates generated successfully in certs/"
