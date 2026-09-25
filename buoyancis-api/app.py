import os
import json
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

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

# 默认沙盒数据文件路径
SANDBOX_PATH = os.path.expanduser("~/Desktop/Buoyancis/sandbox_gocardless.json")

@app.route("/api/verify", methods=["POST"])
def verify_affordability():
    data = request.get_json() or {}
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
    return jsonify({
        "status": res.get("status", "PASS" if res.get("passed") else "FAIL"),
        "rent": res.get("target_rent", rent),
        "required_threshold": res.get("required_threshold", res.get("threshold", rent * 3.0)),
        "pv_discounted_inflows": res.get("pv_discounted_inflows", res.get("pv_inflows", 0.0)),
        "verification_id": f"proof_byc_{os.urandom(4).hex()}",
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "security_metadata": res.get("security_metadata", {
            "engine_version": "v0.2.0-heuristic",
            "anti_gaming_baseline": "Rule A (90-day), Rule B (Outlier Cap), Rule C (Eligibility Filter)",
            "disclaimer": "MVP includes an initial anti-gaming heuristic; source authenticity and adversarial resistance are future security layers."
        }),
        "logs": res.get("processed_logs", res.get("logs", []))
    }), 200

if __name__ == "__main__":
    PORT = 5001
    print(f"🚀 Buoyancis API Engine running on http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=True)