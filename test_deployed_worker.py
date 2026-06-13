import time
import hmac
import hashlib
import json
import urllib.request
import urllib.error

base_url = "https://kheladekho.thevamp-cloud.workers.dev"
secret_key = "production-super-secret-key-fallback-change-me"

print(f"Testing deployed Cloudflare Worker at: {base_url}\n")

def make_request(path, headers=None):
    url = f"{base_url}{path}"
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
            body = json.loads(response.read().decode('utf-8'))
            return status, body
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = json.loads(e.read().decode('utf-8'))
        except:
            body = e.reason
        return status, body
    except Exception as e:
        return 0, str(e)

# 1. Test GET /
print("Testing GET / ...")
status, body = make_request("/")
print(f"Status: {status}")
print(f"Response: {json.dumps(body, indent=2)}\n")

# 2. Test GET /api/v1/health
print("Testing GET /api/v1/health ...")
status, body = make_request("/api/v1/health")
print(f"Status: {status}")
print(f"Response: {json.dumps(body, indent=2)}\n")

# 3. Test GET /api/v1/matches
print("Testing GET /api/v1/matches?limit=2 ...")
status, body = make_request("/api/v1/matches?limit=2")
print(f"Status: {status}")
if isinstance(body, dict) and body.get("success"):
    matches = body["data"].get("matches", [])
    print(f"Found {len(matches)} matches (limit 2).")
    for m in matches:
        print(f"  - {m['team1']['name']} vs {m['team2']['name']} (Status: {m['status']})")
else:
    print(f"Response: {body}")
print()

# 4. Test GET /api/v1/channels
print("Testing GET /api/v1/channels?limit=2 ...")
status, body = make_request("/api/v1/channels?limit=2")
print(f"Status: {status}")
if isinstance(body, dict) and body.get("success"):
    channels = body["data"].get("channels", [])
    print(f"Found {len(channels)} channels.")
    for ch in channels:
        print(f"  - {ch['name']} (Key: {ch['key']}, Status: {ch['status']})")
else:
    print(f"Response: {body}")
print()

# 5. Test GET /api/v1/stats
print("Testing GET /api/v1/stats ...")
status, body = make_request("/api/v1/stats")
print(f"Status: {status}")
print(f"Response: {json.dumps(body, indent=2)}\n")

# 6. Test GET /api/v1/channels/wctveng/stream (Without signature, should be 401)
print("Testing GET /api/v1/channels/wctveng/stream (WITHOUT signature) ...")
status, body = make_request("/api/v1/channels/wctveng/stream")
print(f"Status: {status} (Expected: 401)")
print(f"Response: {json.dumps(body, indent=2)}\n")

# 7. Test GET /api/v1/channels/wctveng/stream (WITH valid signature)
print("Testing GET /api/v1/channels/wctveng/stream (WITH signature) ...")
timestamp = str(int(time.time()))
path = "/api/v1/channels/wctveng/stream"
expected_message = f"{timestamp}:{path}".encode()
signature = hmac.new(
    secret_key.encode(),
    expected_message,
    hashlib.sha256
).hexdigest()

headers = {
    "X-Signature-Token": signature,
    "X-Signature-Timestamp": timestamp
}

status, body = make_request(path, headers=headers)
print(f"Status: {status}")
print(f"Response: {json.dumps(body, indent=2)}\n")
