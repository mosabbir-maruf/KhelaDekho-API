import time
import hmac
import hashlib
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        json_data = response.json()
        assert json_data["success"] is True
        assert "data" in json_data
        assert json_data["data"]["status"] == "ok"
        assert "version" in json_data["data"]

def test_matches_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/v1/matches?limit=5")
        assert response.status_code == 200
        json_data = response.json()
        assert json_data["success"] is True
        assert "matches" in json_data["data"]
        assert len(json_data["data"]["matches"]) <= 5

def test_stream_without_auth_fails():
    with TestClient(app) as client:
        response = client.get("/api/v1/channels/wctveng/stream")
        assert response.status_code == 401
        json_data = response.json()
        assert json_data["success"] is False
        assert json_data["error"]["code"] == "HTTP_401"
        assert "credentials missing" in json_data["error"]["message"]

def test_stream_with_invalid_signature_fails():
    with TestClient(app) as client:
        headers = {
            "X-Signature-Token": "badsignature12345",
            "X-Signature-Timestamp": str(int(time.time()))
        }
        response = client.get("/api/v1/channels/wctveng/stream", headers=headers)
        assert response.status_code == 401
        json_data = response.json()
        assert json_data["success"] is False
        assert "Signature validation failed" in json_data["error"]["message"]

def test_stream_with_expired_signature_fails():
    with TestClient(app) as client:
        # 2 minutes ago
        expired_ts = str(int(time.time()) - 120)
        path = "/api/v1/channels/wctveng/stream"
        expected_message = f"{expired_ts}:{path}".encode()
        signature = hmac.new(
            settings.secret_key.encode(),
            expected_message,
            hashlib.sha256
        ).hexdigest()

        headers = {
            "X-Signature-Token": signature,
            "X-Signature-Timestamp": expired_ts
        }
        response = client.get("/api/v1/channels/wctveng/stream", headers=headers)
        assert response.status_code == 401
        json_data = response.json()
        assert json_data["success"] is False
        assert "expired" in json_data["error"]["message"]

def test_stream_with_valid_signature_passes_auth():
    with TestClient(app) as client:
        timestamp = str(int(time.time()))
        path = "/api/v1/channels/wctveng/stream"
        expected_message = f"{timestamp}:{path}".encode()
        signature = hmac.new(
            settings.secret_key.encode(),
            expected_message,
            hashlib.sha256
        ).hexdigest()

        headers = {
            "X-Signature-Token": signature,
            "X-Signature-Timestamp": timestamp
        }
        response = client.get("/api/v1/channels/wctveng/stream", headers=headers)
        # Since this is an upstream scraper call, it will either return 200, or a bad gateway (502) if upstream is down/token expired.
        # But it should NOT fail with 401 Unauthorized.
        assert response.status_code in (200, 502, 400)
        if response.status_code == 200:
            json_data = response.json()
            assert json_data["success"] is True

if __name__ == "__main__":
    tests = [
        test_health_endpoint,
        test_matches_endpoint,
        test_stream_without_auth_fails,
        test_stream_with_invalid_signature_fails,
        test_stream_with_expired_signature_fails,
        test_stream_with_valid_signature_passes_auth,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            print(f"Running {test.__name__}...")
            test()
            print(f"  {test.__name__} PASSED")
            passed += 1
        except AssertionError as e:
            print(f"  {test.__name__} FAILED (AssertionError)")
            failed += 1
        except Exception as e:
            print(f"  {test.__name__} ERROR: {str(e)}")
            failed += 1
            
    print(f"\nTest Run Summary: {passed} passed, {failed} failed.")
    if failed > 0:
        exit(1)
