# bank-attribute-service

High-throughput transaction → ML feature pipeline.  
Accepts a batch of raw bank transactions and returns per-account attribute vectors in **under ~0.7s end-to-end on 100k records.**.

---

## Architecture

```
POST /attributes
      │
      ▼
 AttributeRequest (Pydantic v2)
      │
      ▼
 Normalizer  ──── dedup on transaction_id
      │            dtype enforcement
      ▼
 Polars Engine ─── single lazy group_by + agg
      │             all metrics in one pass
      ▼
 Redis Cache  ──── SHA-256 key of sorted payload
      │             TTL: 5 min (configurable)
      ▼
 AttributeResponse
```

**Stack:** FastAPI · Polars (lazy + streaming) · Pydantic v2 · Redis · pytest

---

## Quick Start

### Option A – Local (no Docker)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) start Redis for caching
docker run -d -p 6379:6379 redis:7-alpine

# 3. Start the service
uvicorn app.main:app --reload

# 4. Generate test data
python scripts/generate_data.py

# 5. POST 100k transactions
curl -s -X POST http://localhost:8000/attributes \
     -H 'Content-Type: application/json' \
     -d @data/transactions_100k.json \
     | python -m json.tool | head -60
```

### Option B – Docker Compose (Redis + App)

```bash
docker compose up --build
```

---

## API

### `GET /health`

```json
{ "status": "ok", "version": "1.0.0" }
```

### `POST /attributes`

**Request body**

```json
{
  "transactions": [
    {
      "transaction_id": "TXN-001",
      "account_id":     "ACC-000001",
      "amount":         -45.99,
      "transaction_date": "2024-03-15",
      "merchant_category": "GROCERY",
      "channel": "POS"
    }
  ]
}
```

**Response**

```json
{
  "attributes": {
    "ACC-000001": {
      "txn_count": 1,
      "total_credit": 0.0,
      "total_debit": -45.99,
      "net_flow": -45.99,
      "avg_txn_amount": -45.99,
      "days_since_last_txn": 76,
      "days_since_first_txn": 76,
      "active_days": 1,
      "top_category": "GROCERY",
      "category_count": 1,
      "grocery_spend": -45.99,
      "salary_credit": 0.0,
      "pos_count": 1,
      "ach_count": 0,
      "atm_count": 0,
      "wire_count": 0,
      "digital_ratio": 0.0,
      "cashflow_net": -45.99,
      "cashflow_credit": 0.0,
      "cashflow_debit": -45.99,
      "cashflow_txn_count": 1
    }
  },
  "meta": {
    "transaction_count": 1,
    "account_count": 1,
    "metrics_computed": ["transaction_volume", "recency", "spend_category", "channel_behaviour", "cash_flow"],
    "elapsed_seconds": 0.012,
    "cache_hit": false
  }
}
```

---

## Metrics

| Metric | Outputs | Description |
|--------|---------|-------------|
| `transaction_volume` | `txn_count`, `total_credit`, `total_debit`, `net_flow`, `avg_txn_amount` | Volume and monetary flow |
| `recency` | `days_since_last_txn`, `days_since_first_txn`, `active_days` | Temporal activity |
| `spend_category` | `top_category`, `category_count`, `grocery_spend`, `salary_credit` | MCC distribution |
| `channel_behaviour` | `pos_count`, `ach_count`, `atm_count`, `wire_count`, `digital_ratio` | Payment channel mix |
| `cash_flow` | `cashflow_net`, `cashflow_credit`, `cashflow_debit`, `cashflow_txn_count` | Rolling-window cash flow |

### Adding a metric (one line)

```python
# In app/registry.py or anywhere that imports metric_registry:
from app.registry import metric_registry, CashFlowMetric
metric_registry.register(CashFlowMetric(window_days=14, min_transactions=2))
```

Or write your own:

```python
class MyMetric(BaseMetric):
    name = "my_metric"
    output_columns = ["my_col"]

    def expressions(self) -> list[pl.Expr]:
        return [pl.col("amount").std().alias("my_col")]

metric_registry.register(MyMetric())
```

---

## Tests

```bash
pytest -v                         # all tests
pytest tests/test_benchmark.py -v -s   # benchmark with timing output
pytest tests/test_determinism.py -v    # determinism suite
pytest tests/test_metrics.py -v        # metric correctness
```

Expected output:

```
tests/test_benchmark.py::TestBenchmark::test_full_pipeline_100k_under_4s PASSED
[BENCHMARK] 100k rows | normalise=0.412s | engine=1.834s | total=2.246s
```

---

## Configuration

All settings can be overridden via environment variables or a `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `MAX_BATCH_SIZE` | `200000` | Max transactions per request |
| `CACHE_TTL_SECONDS` | `300` | Redis TTL (5 min) |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` |

---

## Loom Demo Script

**Scene 1 – Throughput**
```bash
# Terminal 1: start service
uvicorn app.main:app

# Terminal 2: generate + POST 100k records
python scripts/generate_data.py
time curl -s -X POST http://localhost:8000/attributes \
     -H 'Content-Type: application/json' \
     -d @data/transactions_100k.json > /dev/null
```

**Scene 2 – Add a metric in one line**
Open `app/registry.py`, scroll to the bottom, and add:
```python
metric_registry.register(CashFlowMetric(window_days=14, min_transactions=2))
```
Re-run the curl. Show `cashflow_net` (14-day window) in the JSON response.

**Scene 3 – Tests**
```bash
pytest -v --tb=short
```

---

## Project Structure

```
bank-attribute-service/
├── app/
│   ├── main.py          # FastAPI entry
│   ├── models.py        # Pydantic schemas
│   ├── normalizer.py    # Dedup + dtype enforcement
│   ├── registry.py      # Metric registry + built-in metrics
│   ├── engine.py        # Polars computation engine
│   ├── cache.py         # Redis layer (graceful fallback)
│   └── config.py        # Pydantic Settings
├── tests/
│   ├── conftest.py
│   ├── test_determinism.py
│   ├── test_metrics.py
│   └── test_benchmark.py
├── scripts/
│   └── generate_data.py  # 100k synthetic transactions
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```
