import os
import json
import hmac
import hashlib
import secrets
import logging
import math
from urllib.parse import quote, urlencode
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin
import requests
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

load_dotenv()

TINK_CLIENT_ID = os.environ.get("TINK_CLIENT_ID", "").strip()
TINK_CLIENT_SECRET = os.environ.get("TINK_CLIENT_SECRET", "").strip()
TINK_REDIRECT_URI = os.environ.get("TINK_REDIRECT_URI", "https://buoyancis.com/callback").strip()
TINK_ENV = os.environ.get("TINK_ENV", "sandbox").strip().lower()
TINK_TOKEN_URL = "https://api.tink.com/api/v1/oauth/token"
TINK_TRANSACTIONS_URL = "https://api.tink.com/data/v2/transactions"
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


def _tink_state_serializer():
    return URLSafeTimedSerializer(
        TINK_CLIENT_SECRET or PAYLOAD_SIGNING_SECRET,
        salt="tink-oauth-state",
    )


def _build_signed_payload(result, provider_name, source, currency=None, include_logs=True):
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30)
    payload = {
        "status": result.get("status", "PASS" if result.get("passed") else "FAIL"),
        "rent": result.get("target_rent", 1200.0),
        "required_threshold": result.get("required_threshold", result.get("threshold", 3600.0)),
        "pv_discounted_inflows": result.get("pv_discounted_inflows", result.get("pv_inflows", 0.0)),
        "verification_id": f"proof_byc_{os.urandom(4).hex()}",
        "timestamp": int(now.timestamp() * 1000),
        "nonce": secrets.token_urlsafe(16),
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "security_metadata": result.get("security_metadata", {}),
        "provider": provider_name,
        "source": source,
        "mock_source": {"provider": provider_name, "source": source},
    }
    if include_logs:
        payload["logs"] = result.get("processed_logs", result.get("logs", []))
    if currency:
        payload["currency"] = currency
    payload["payload_hash"] = _payload_digest(payload)
    return payload


def _normalize_tink_transactions(response_data):
    if isinstance(response_data, list):
        transactions = response_data
    elif isinstance(response_data, dict):
        transactions = response_data.get("transactions", response_data.get("data", []))
    else:
        transactions = []
    if isinstance(transactions, dict):
        transactions = transactions.get("booked", transactions.get("items", []))
    if not isinstance(transactions, list):
        return [], set()

    normalized = []
    currencies = set()
    for transaction in transactions:
        if not isinstance(transaction, dict):
            continue
        amount = transaction.get("amount", transaction.get("transactionAmount", 0))
        if isinstance(amount, dict):
            currency = amount.get("currencyCode") or amount.get("currency")
            amount = amount.get("value", amount.get("amount", 0))
        else:
            currency = transaction.get("currencyCode") or transaction.get("currency")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            continue
        if currency:
            currencies.add(str(currency).upper())

        direction = str(transaction.get("creditDebitIndicator", transaction.get("direction", ""))).upper()
        if direction == "DEBIT":
            amount = -abs(amount)
        elif direction == "CREDIT":
            amount = abs(amount)

        tx_date = (transaction.get("bookingDate") or transaction.get("date") or
                   transaction.get("transactionDate") or transaction.get("valueDate"))
        if not tx_date:
            continue
        normalized.append({
            "date": str(tx_date)[:10],
            "amount": amount,
            "category": transaction.get("description") or transaction.get("remittanceInformationUnstructured") or "",
            "is_self_transfer": bool(transaction.get("isSelfTransfer", False)),
        })
    return normalized, currencies

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
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid request body"}), 400

    provider_name = data.get("provider") or "Revolut"
    providers = {
        "revolut": "Revolut",
        "wise": "Wise",
        "swedbank": "Swedbank",
        "sandbox_mock": "Sandbox Mock",
    }
    if not isinstance(provider_name, str):
        return jsonify({"error": "Unsupported provider"}), 400
    provider_name = providers.get(provider_name.strip().lower())
    if not provider_name:
        return jsonify({"error": "Unsupported provider"}), 400
    print(f"[DEBUG] Received provider: {provider_name}")
    currency = data.get("currency", "EUR")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        return jsonify({"error": "Invalid currency"}), 400
    currency = currency.upper()

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

    payload = _build_signed_payload(
        res,
        provider_name,
        f"{provider_name} AISP Verified",
        currency,
    )
    print("--> FINAL PAYLOAD KEYS:", list(payload.keys()))
    return jsonify(payload)


@app.route("/api/tink/auth-url", methods=["POST"])
def tink_auth_url():
    if not TINK_CLIENT_ID:
        return jsonify({
            "mode": "mock",
            "status": "fallback",
            "message": "Tink credentials are not configured; continue with Mock AISP.",
        }), 200
    if TINK_ENV not in {"sandbox", "production"}:
        return jsonify({"error": "TINK_ENV must be sandbox or production"}), 500

    request_data = request.get_json(silent=True) or {}
    if not isinstance(request_data, dict):
        return jsonify({"error": "Invalid request body"}), 400
    try:
        rent = float(request_data.get("rent", 1200.0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid rent"}), 400
    if not math.isfinite(rent) or rent <= 0:
        return jsonify({"error": "Invalid rent"}), 400
    currency = request_data.get("currency", "SEK")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        return jsonify({"error": "Invalid currency"}), 400
    currency = currency.upper()
    bank_name = request_data.get("provider", "Revolut")
    if not isinstance(bank_name, str) or len(bank_name) > 80:
        return jsonify({"error": "Invalid bank provider"}), 400
    bank_name = bank_name.strip() or "Revolut"

    signed_state = _tink_state_serializer().dumps({
        "nonce": secrets.token_urlsafe(24),
        "rent": rent,
        "currency": currency,
        "bank_name": bank_name,
        "environment": TINK_ENV,
    })
    query = urlencode({
        "client_id": TINK_CLIENT_ID,
        "redirect_uri": TINK_REDIRECT_URI,
        "scope": "accounts:read,transactions:read",
        "market": "SE",
        "locale": "en_US",
        "state": signed_state,
    })
    return jsonify({
        "mode": "tink",
        "status": "ready",
        "auth_url": f"https://link.tink.com/1.0/authorize/?{query}",
        "environment": TINK_ENV,
    }), 200


@app.route("/api/tink/callback", methods=["GET", "POST"])
def tink_callback():
    callback_data = request.get_json(silent=True) or {} if request.method == "POST" else request.args
    if callback_data.get("error"):
        return jsonify({"error": "Tink authorization was not completed"}), 400
    authorization_code = callback_data.get("code")
    state = callback_data.get("state")
    if not authorization_code or not state:
        return jsonify({"error": "Missing Tink authorization code or state"}), 400
    if not TINK_CLIENT_ID or not TINK_CLIENT_SECRET:
        return jsonify({"error": "Tink credentials are not configured"}), 503

    try:
        state_data = _tink_state_serializer().loads(state, max_age=900)
    except SignatureExpired:
        return jsonify({"error": "Tink authorization state expired"}), 400
    except BadSignature:
        return jsonify({"error": "Invalid Tink authorization state"}), 400

    try:
        rent = float(state_data["rent"])
        currency = str(state_data["currency"]).upper()
        bank_name = str(state_data.get("bank_name") or "Revolut")[:80]
        if state_data.get("environment") != TINK_ENV:
            return jsonify({"error": "Tink environment changed during authorization"}), 400
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid Tink authorization state"}), 400

    try:
        token_response = requests.post(
            TINK_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "client_id": TINK_CLIENT_ID,
                "client_secret": TINK_CLIENT_SECRET,
                "redirect_uri": TINK_REDIRECT_URI,
            },
            timeout=15,
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise ValueError("Missing user access token")

        transactions_response = requests.get(
            TINK_TRANSACTIONS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        transactions_response.raise_for_status()
        tink_data = transactions_response.json()
    except (requests.RequestException, ValueError) as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logging.warning("Tink callback data request failed (HTTP %s)", status_code or "unknown")
        return jsonify({"error": "Tink data retrieval failed"}), 502

    transactions, currencies = _normalize_tink_transactions(tink_data)
    if len(currencies) > 1:
        return jsonify({"error": "Mixed transaction currencies are not supported for one affordability score"}), 422
    if currencies and currency not in currencies:
        return jsonify({"error": f"Currency mismatch: rent is {currency}; automatic FX conversion is not configured"}), 422

    result = calculate_buoyancis_score(transactions, rent)
    provider_name = f"Tink AISP - {bank_name}"
    payload = _build_signed_payload(
        result,
        provider_name,
        "Tink AISP Verified",
        currency,
        include_logs=False,
    )
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
