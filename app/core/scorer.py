def score_account(attrs: dict) -> dict:
    score = 100

    # Penalise negative cash flow
    if attrs.get("net_flow", 0) < 0:
        score -= 20

    # Reward salary income
    if attrs.get("salary_credit", 0) > 5000:
        score += 15

    # Penalise inactivity
    if attrs.get("days_since_last_txn", 999) > 90:
        score -= 15

    # Reward digital behaviour
    if attrs.get("digital_ratio", 0) > 0.4:
        score += 10

    # Short-term stress signal
    if attrs.get("cashflow_net", 0) < -500:
        score -= 10

    # Overdraft risk
    if attrs.get("balance", {}).get("overdraft_risk", 0) > 200:
        score -= 15

    score = max(0, min(100, score))

    return {
        "score": score,
        "decision": "APPROVE"
        if score >= 70
        else "REVIEW"
        if score >= 50
        else "DECLINE",
        "risk_tier": "LOW" if score >= 70 else "MEDIUM" if score >= 50 else "HIGH",
    }
