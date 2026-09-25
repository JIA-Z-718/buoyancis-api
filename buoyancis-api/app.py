import os
import json
import hmac
import hashlib
import secrets
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin

TINK_CLIENT_ID = os.environ.get("TINK_CLIENT_ID", "sandbox_mock_client_id")
TINK_CLIENT_SECRET = os.environ.get("TINK_CLIENT_SECRET", "sandbox_mock_secret")
# Configure a private, stable value in production; this fallback is for local sandbox use only.
PAYLOAD_SIGNING_SECRET = os.environ.get("PAYLOAD_SIGNING_SECRET", "sandbox_mock_signing_secret")
ALLOWED_FRONTEND_ORIGIN = "https://buoyancis.com"


def _payload_digest(payload):
    unsigned_payload = {key: value for key, value in payload.items() if key != "payload_hash"}
    canonical_payload = json.dumps(unsigned_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(
        PAYLOAD_SIGNING_SECRET.encode("utf-8"),
        canonical_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

app = Flask(__name__)
CORS(app)  # 允许跨域请求
# 从 buoyancis_engine 导入最新的的核心计算引擎
# 如果你保留了 parse_gocardless_and_evaluate 函数，这里同时兼容导入
try:
    from buoyancis_engine import calculate_buoyancis_score
except ImportError:
    from buoyancis_engine import parse_gocardless_and_evaluate as calculate_buoyancis_score


app = Flask(__name__)
CORS(app)  # 允许前端 HTML 跨域请求


@app.route("/health", methods=["GET"])
@cross_origin(origins=["https://buoyancis.com"])
def health():
    return jsonify({
        "status": "ok",
        "service": "buoyancis-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


@app.route("/api/v1/auth/sandbox-link", methods=["GET"])
@cross_origin(origins=[ALLOWED_FRONTEND_ORIGIN])
def sandbox_link():
    origin = request.headers.get("Origin")
    if origin and origin != ALLOWED_FRONTEND_ORIGIN:
        return jsonify({"error": "Origin not allowed"}), 403

    return jsonify({
        "provider": "Tink Sandbox",
        "auth_url": "https://link.tink.com/1.0/authorize/?client_id=" + quote(TINK_CLIENT_ID, safe=""),
        "status": "ready",
    }), 200

# 默认沙盒数据文件路径
SANDBOX_PATH = os.path.expanduser("~/Desktop/Buoyancis/sandbox_gocardless.json")

@app.route("/api/verify", methods=["POST"])
def verify_affordability():
    data = request.get_json() or {}
    provider = data.get("provider", "sandbox_mock")
    mock_sources = {
        "revolut": {"provider": "Revolut", "source": "Revolut AISP Verified"},
        "wise": {"provider": "Wise", "source": "Wise AISP Verified"},
        "swedbank": {"provider": "Swedbank", "source": "Swedbank AISP Verified"},
        "sandbox_mock": {"provider": "Sandbox Mock", "source": "Sandbox Mock AISP Verified"},
    }
    if not isinstance(provider, str) or provider not in mock_sources:
        return jsonify({"error": "Unsupported provider"}), 400

    rent = float(data.get("rent", 1200.0))
    
    # 优先读取前端传入的数据，若无则读取本地 GoCardless 沙盒 JSON 文件
    gocardless_data = None
    if "transactions_json" in data:
        gocardless_data = data["transactions_json"]
    else:
        try:
            if os.path.exists(SANDBOX_PATH):
                with open(SANDBOX_PATH, "r", encoding="utf-8") as f:
                    gocardless_data = json.load(f)
            else:
                # 兜底 Mock 数据，确保无沙盒文件时也能平滑运行
                gocardless_data = [
                    {"date": "2026-09-01", "amount": 3500.0, "category": "salary", "is_self_transfer": False},
                    {"date": "2026-08-01", "amount": 3500.0, "category": "salary", "is_self_transfer": False},
                    {"date": "2026-07-01", "amount": 3500.0, "category": "salary", "is_self_transfer": False},
                    {"date": "2026-08-15", "amount": 1000.0, "category": "refund", "is_self_transfer": False},
                    {"date": "2026-08-20", "amount": 2000.0, "category": "transfer_internal", "is_self_transfer": True}
                ]
        except Exception as e:
            return jsonify({"error": f"Failed to load sandbox data: {str(e)}"}), 500

    # 调用核心评估引擎 (支持直接传入列表或解析 GoCardless 结构)
    if isinstance(gocardless_data, dict) and "transactions" in gocardless_data:
        raw_txs = gocardless_data["transactions"].get("booked", [])
    elif isinstance(gocardless_data, list):
        raw_txs = gocardless_data
    else:
        raw_txs = []

    res = calculate_buoyancis_score(raw_txs, rent)

    # 动态生成时间戳
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30)

    # 构建标准化 response
    payload = {
        "status": res.get("status", "PASS" if res.get("passed") else "FAIL"),
        "rent": res.get("target_rent", rent),
        "required_threshold": res.get("required_threshold", res.get("threshold", rent * 3.0)),
        "pv_discounted_inflows": res.get("pv_discounted_inflows", res.get("pv_inflows", 0.0)),
        "verification_id": f"proof_byc_{os.urandom(4).hex()}",
        "provider": provider,
        "mock_source": mock_sources[provider],
        "timestamp": int(now.timestamp() * 1000),
        "nonce": secrets.token_urlsafe(16),
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "security_metadata": res.get("security_metadata", {
            "engine_version": "v0.2.0-heuristic",
            "anti_gaming_baseline": "Rule A (90-day), Rule B (Outlier Cap), Rule C (Eligibility Filter)",
            "disclaimer": "MVP includes an initial anti-gaming heuristic; source authenticity and adversarial resistance are future security layers."
        }),
        "logs": res.get("processed_logs", res.get("logs", []))
    }
    payload["payload_hash"] = _payload_digest(payload)
    return jsonify(payload), 200


@app.route("/api/verify-payload", methods=["POST"])
def verify_payload():
    data = request.get_json(silent=True) or {}
    payload = data.get("payload", data)
    if not isinstance(payload, dict) or not isinstance(payload.get("payload_hash"), str):
        return jsonify({"status": "INVALID", "message": "Missing or invalid signed payload"}), 400

    expected_hash = _payload_digest(payload)
    if not hmac.compare_digest(payload["payload_hash"], expected_hash):
        return jsonify({"status": "INVALID", "message": "Payload integrity check failed"}), 400

    timestamp = payload.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return jsonify({"status": "INVALID", "message": "Invalid payload timestamp"}), 400
    if not isinstance(payload.get("nonce"), str) or not payload["nonce"]:
        return jsonify({"status": "INVALID", "message": "Invalid payload nonce"}), 400

    age_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - timestamp
    if age_ms < 0:
        return jsonify({"status": "INVALID", "message": "Payload timestamp is in the future"}), 400
    if age_ms > 30 * 24 * 60 * 60 * 1000:
        return jsonify({
            "status": "EXPIRED",
            "message": "Over 30 days old",
            "eligibility_status": payload.get("status"),
            "verification_id": payload.get("verification_id"),
        }), 200

    return jsonify({
        "status": "PASS",
        "message": "Payload signature and timestamp are valid",
        "eligibility_status": payload.get("status"),
        "verification_id": payload.get("verification_id"),
    }), 200

if __name__ == "__main__":
    PORT = 5001
    print(f"🚀 Buoyancis API Engine running on http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=True)
