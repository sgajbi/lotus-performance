# 🚀 Quick Start Guide

This guide will get you from **zero to your first successful API call in under two minutes**.  
The goal is to calculate a simple **Time-Weighted Return (TWR)** for a portfolio.

---

## 1. The Endpoint

All performance calculations are **POST requests** sent to endpoints under the `/performance/` path.  

For this example, we will use:

```

POST /performance/twr

````

---

## 2. The Request

You will need to provide a **JSON payload** in the body of your POST request.  
The minimum required fields are:

- `portfolio_id`: A unique identifier for your portfolio.  
- `performance_start_date`: The inception date of the portfolio.  
- `report_end_date`: The last day of the period you want to analyze.  
- `metric_basis`: Whether to calculate returns `"NET"` (after fees) or `"GROSS"` (before fees).  
- `period_type`: The time frame, such as `"YTD"` (Year-to-Date).  
- `daily_data`: An array containing the daily market values.  

---

## 3. Example curl Command

Copy and paste the following command into your terminal.  
It sends a request with a minimal, valid payload to a locally running instance of the service
through the canonical RFC-0071 dev ingress identity.

```bash
curl -X POST "http://performance.dev.lotus/performance/twr" \
-H "Content-Type: application/json" \
-d '{
  "portfolio_id": "QUICK_START_01",
  "performance_start_date": "2024-12-31",
  "report_end_date": "2025-01-02",
  "metric_basis": "NET",
  "period_type": "YTD",
  "frequencies": ["daily"],
  "daily_data": [
    {
      "perf_date": "2025-01-01",
      "begin_mv": 100000.0,
      "end_mv": 101000.0
    },
    {
      "perf_date": "2025-01-02",
      "begin_mv": 101000.0,
      "end_mv": 102010.0
    }
  ]
}'
````

---

## 4. The Response (Excerpt)

If successful, you will receive a **200 OK** response with a JSON body.
The key part is the `breakdowns` object:

```json
{
  "calculation_id": "uuid-goes-here...",
  "portfolio_id": "QUICK_START_01",
  "breakdowns": {
    "daily": [
      {
        "period": "2025-01-01",
        "summary": {
          "period_return_pct": 1.0
        }
      },
      {
        "period": "2025-01-02",
        "summary": {
          "period_return_pct": 1.0
        }
      }
    ]
  },
  "portfolio_return": {
    "local": 2.01,
    "fx": 0.0,
    "base": 2.01
  }
  // ...meta, diagnostics, and audit blocks...
}
```

---

## 🎉 Congratulations!

You have successfully calculated a **Time-Weighted Return (TWR)**.
The total return for the period was **2.01%**, which is the result of compounding the two daily 1.0% returns.

 
