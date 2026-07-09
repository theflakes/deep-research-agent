#!/usr/bin/env bash
set -euo pipefail

PROXY="socks5h://tor-proxy:9050"

echo "========================================"
echo "Testing SOCKS5 connectivity"
echo "========================================"

python3 <<'PY'
import socket

try:
    s = socket.create_connection(("tor-proxy",9050),timeout=5)
    s.sendall(b"\x05\x01\x00")
    print("SOCKS reply:", s.recv(2))
    s.close()
except Exception as e:
    print("FAILED:", e)
PY

echo
echo "========================================"
echo "Testing Tor IP"
echo "========================================"

python3 <<PY
import httpx

proxy="$PROXY"

try:
    with httpx.Client(proxy=proxy,timeout=30) as c:
        r=c.get("https://check.torproject.org/api/ip")
        print(r.text)
except Exception as e:
    print(e)
PY

echo
echo "========================================"
echo "Testing httpbin"
echo "========================================"

python3 <<PY
import httpx

proxy="$PROXY"

try:
    with httpx.Client(proxy=proxy,timeout=30) as c:
        r=c.get("https://httpbin.org/ip")
        print(r.text)
except Exception as e:
    print(e)
PY

echo
echo "========================================"
echo "Testing ifconfig.me"
echo "========================================"

python3 <<PY
import httpx

proxy="$PROXY"

try:
    with httpx.Client(proxy=proxy,timeout=30) as c:
        r=c.get("https://ifconfig.me")
        print(r.text)
except Exception as e:
    print(e)
PY

echo
echo "========================================"
echo "Testing Reuters (expected to possibly fail)"
echo "========================================"

python3 <<PY
import httpx

proxy="$PROXY"

try:
    with httpx.Client(
        proxy=proxy,
        timeout=30,
        follow_redirects=True,
        headers={
            "User-Agent":"Mozilla/5.0",
            "Accept":"text/html"
        }
    ) as c:
        r=c.get("https://www.reuters.com/")
        print("Status:",r.status_code)
        print(r.text[:500])
except Exception as e:
    print(e)
PY

echo
echo "========================================"
echo "Done"
echo "========================================"


echo "===== Proxy environment ====="
env | grep -i proxy || true

echo
echo "===== DNS ====="
getent hosts tor-proxy

echo
echo "===== Routing ====="
ip route

echo
echo "===== Public IP (direct, should NOT match Tor) ====="
curl -s https://ifconfig.me || true

echo
echo "===== Public IP through Tor ====="
curl --socks5-hostname tor-proxy:9050 -s https://ifconfig.me || true

echo
echo "===== Difference ====="
echo "If the two IPs are identical, Tor is NOT being used."
