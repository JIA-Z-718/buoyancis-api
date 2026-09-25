import math
from datetime import datetime, timedelta

def calculate_buoyancis_score(transactions, target_rent, evaluation_date=None):
    """
    Buoyancis Core Present Value (PV) Engine with Heuristic Anti-Gaming Controls
    Supports both GoCardless ISO 20022 JSON schema and simple Mock dicts.
    """
    if evaluation_date is None:
        # 默认使用评估当天的真实日期
        evaluation_date = datetime.now()

    LAMBDA = 0.0077  # Half-life weight decaying factor (~0.5 at day 90)
    TOTAL_PV = 0.0

    # 1. 提取金额的通用解析器
    def parse_amount(tx):
        if 'transactionAmount' in tx and isinstance(tx['transactionAmount'], dict):
            return float(tx['transactionAmount'].get('amount', 0.0))
        return float(tx.get('amount', 0.0))

    # 2. 提取日期的通用解析器
    def parse_date(tx):
        date_str = tx.get('bookingDate') or tx.get('valueDate') or tx.get('date')
        if not date_str:
            return None
        clean_date_str = date_str.split('T')[0]
        try:
            return datetime.strptime(clean_date_str, "%Y-%m-%d")
        except ValueError:
            return None

    # 计算大额异常阈值 (Rule B Baseline)
    inflow_amounts = [parse_amount(tx) for tx in transactions if parse_amount(tx) > 0]
    avg_inflow = (sum(inflow_amounts) / len(inflow_amounts)) if inflow_amounts else 0.0
    outlier_cap = 3.0 * avg_inflow if avg_inflow > 0 else float('inf')

    processed_logs = []

    for tx in transactions:
        amount = parse_amount(tx)
        tx_date = parse_date(tx)

        if not tx_date:
            continue

        tx_type = str(tx.get('category', tx.get('remittanceInformationUnstructured', ''))).lower()
        is_self_transfer = tx.get('is_self_transfer', False)

        delta_t = (evaluation_date - tx_date).days

        # Rule A: 90-Day Window Hard Gate
        if delta_t < 0 or delta_t > 90:
            continue

        # Rule C: Transaction Eligibility (排除非收入、自转账、退款)
        if amount <= 0 or is_self_transfer or 'refund' in tx_type or 'transfer_internal' in tx_type:
            continue

        # Rule B: Outlier Limit Adjustment
        eligible_amount = min(amount, outlier_cap) if outlier_cap > 0 else amount

        # Exponential Time Discounting W(t) = e^(-lambda * delta_t)
        weight = math.exp(-LAMBDA * delta_t)
        pv_contribution = eligible_amount * weight
        TOTAL_PV += pv_contribution

        processed_logs.append({
            "date": tx_date.strftime("%Y-%m-%d"),
            "raw_amount": amount,
            "eligible_amount": eligible_amount,
            "delta_days": delta_t,
            "weight": round(weight, 4),
            "pv_contribution": round(pv_contribution, 2)
        })

    required_threshold = 3.0 * target_rent
    is_passed = TOTAL_PV >= required_threshold

    return {
        "status": "PASS" if is_passed else "FAIL",
        "pv_discounted_inflows": round(TOTAL_PV, 2),
        "required_threshold": round(required_threshold, 2),
        "target_rent": target_rent,
        "security_metadata": {
            "engine_version": "v0.2.0-heuristic",
            "anti_gaming_baseline": "Rule A (90-day), Rule B (Outlier Cap), Rule C (Eligibility Filter)",
            "disclaimer": "MVP includes an initial anti-gaming heuristic; source authenticity and adversarial resistance are future security layers."
        },
        "processed_logs": processed_logs
    }