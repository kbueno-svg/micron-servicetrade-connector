import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query

SERVICE_TRADE_BASE = os.getenv("SERVICETRADE_BASE_URL", "https://api.servicetrade.com/api").rstrip("/")
CLIENT_ID = os.getenv("SERVICETRADE_CLIENT_ID")
CLIENT_SECRET = os.getenv("SERVICETRADE_CLIENT_SECRET")
CONNECTOR_API_KEY = os.getenv("CONNECTOR_API_KEY")

app = FastAPI(title="Micron ServiceTrade Connector", version="1.0.1")

_token_cache: Dict[str, Any] = {"token": None, "expires_at": 0}


def _require_config() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="ServiceTrade credentials are not configured")


def _require_connector_key(x_connector_key: Optional[str] = Header(default=None)) -> None:
    if not CONNECTOR_API_KEY:
        raise HTTPException(status_code=500, detail="Connector API key is not configured")
    if x_connector_key != CONNECTOR_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _get_token() -> str:
    _require_config()
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{SERVICE_TRADE_BASE}/oauth2/token",
            json={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail="ServiceTrade authentication failed")
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail="ServiceTrade did not return an access token")
    expires_in = int(data.get("expires_in", 3600))
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + expires_in
    return token


async def _st_get(path: str, params: Optional[dict] = None) -> dict:
    token = await _get_token()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{SERVICE_TRADE_BASE}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail="ServiceTrade request failed")
    return r.json()


def _hours(seconds: int | float | None) -> float:
    return round((seconds or 0) / 3600, 2)


@app.get("/health")
async def health():
    return {"ok": True, "service": "micron-servicetrade-connector", "version": "1.0.1"}


@app.get("/whoami", dependencies=[Depends(_require_connector_key)])
async def whoami():
    return await _st_get("/oauth2/userinfo")


@app.get("/jobs", dependencies=[Depends(_require_connector_key)])
async def jobs(
    limit: int = Query(20, ge=1, le=100),
    page: int = Query(1, ge=1),
    status: Optional[str] = None,
):
    params: Dict[str, Any] = {"limit": limit, "page": page}
    if status:
        params["status"] = status
    return await _st_get("/job", params=params)


@app.get("/jobs/{job_id}", dependencies=[Depends(_require_connector_key)])
async def job(job_id: int):
    return await _st_get(f"/job/{job_id}")


@app.get("/jobs/{job_id}/items", dependencies=[Depends(_require_connector_key)])
async def job_items(job_id: int):
    return await _st_get("/jobitem", params={"jobId": job_id})


@app.get("/jobs/{job_id}/invoices", dependencies=[Depends(_require_connector_key)])
async def job_invoices(job_id: int):
    return await _st_get("/invoice", params={"jobId": job_id})


@app.get("/jobs/{job_id}/clock", dependencies=[Depends(_require_connector_key)])
async def job_clock(job_id: int):
    return await _st_get(f"/job/{job_id}/clockevent")


@app.get("/jobs/{job_id}/labor-summary", dependencies=[Depends(_require_connector_key)])
async def labor_summary(job_id: int):
    raw = await _st_get(f"/job/{job_id}/clockevent")
    data = raw.get("data", {})
    activity = data.get("activityTime", {})
    summary = {
        "jobId": job_id,
        "onsiteHours": _hours(activity.get("onsite")),
        "enrouteHours": _hours(activity.get("enroute")),
        "offsiteHours": _hours(activity.get("offsite")),
        "breakHours": _hours(activity.get("onbreak")),
    }
    summary["totalJobHours"] = round(
        summary["onsiteHours"] + summary["enrouteHours"] + summary["offsiteHours"], 2
    )

    per_user: Dict[str, Dict[str, Any]] = {}
    for pair in data.get("pairedEvents", []):
        start = pair.get("start") or {}
        user = start.get("user") or {}
        name = user.get("name") or str(user.get("id"))
        activity_name = start.get("activity") or "unknown"
        elapsed = pair.get("elapsedTime") or 0
        row = per_user.setdefault(
            name,
            {"userId": user.get("id"), "name": name, "activities": {}, "totalHours": 0},
        )
        row["activities"][activity_name] = round(
            row["activities"].get(activity_name, 0) + elapsed / 3600, 2
        )
        row["totalHours"] = round(row["totalHours"] + elapsed / 3600, 2)

    summary["technicians"] = list(per_user.values())
    return summary


@app.get("/jobs/{job_id}/profitability", dependencies=[Depends(_require_connector_key)])
async def profitability(job_id: int, loaded_labor_rate: Optional[float] = Query(None, ge=0)):
    job_data = (await _st_get(f"/job/{job_id}")).get("data", {})
    items_data = (await _st_get("/jobitem", params={"jobId": job_id})).get("data", {})
    invoices_data = (await _st_get("/invoice", params={"jobId": job_id})).get("data", {})
    clock_data = (await _st_get(f"/job/{job_id}/clockevent")).get("data", {})

    activity = clock_data.get("activityTime", {})
    total_job_hours = (
        activity.get("onsite", 0) + activity.get("enroute", 0) + activity.get("offsite", 0)
    ) / 3600

    item_cost = 0.0
    missing_cost_items = 0
    for item in items_data.get("jobItems", []):
        cost = item.get("cost")
        qty = item.get("quantity") or 0
        if cost is None:
            missing_cost_items += 1
            continue
        item_cost += float(cost) * float(qty)

    invoice_revenue = 0.0
    for inv in invoices_data.get("invoices", []):
        for key in ("totalPrice", "total", "subtotal"):
            if isinstance(inv.get(key), (int, float)):
                invoice_revenue += float(inv[key])
                break

    estimated_revenue = job_data.get("estimatedPrice")
    revenue = invoice_revenue or (
        float(estimated_revenue) if estimated_revenue is not None else 0.0
    )
    labor_cost = (
        round(total_job_hours * loaded_labor_rate, 2)
        if loaded_labor_rate is not None
        else None
    )
    known_cost = round(item_cost + (labor_cost or 0), 2)
    gross_profit = round(revenue - known_cost, 2) if revenue else None
    gross_margin = (
        round(gross_profit / revenue * 100, 2)
        if revenue and gross_profit is not None
        else None
    )

    return {
        "jobId": job_id,
        "jobNumber": job_data.get("number"),
        "jobName": job_data.get("name"),
        "status": job_data.get("status"),
        "revenue": {
            "invoiceRevenue": round(invoice_revenue, 2),
            "estimatedRevenue": estimated_revenue,
            "selectedRevenue": round(revenue, 2),
            "basis": "invoice" if invoice_revenue else "estimatedPrice",
        },
        "labor": {
            "onsiteHours": _hours(activity.get("onsite")),
            "enrouteHours": _hours(activity.get("enroute")),
            "offsiteHours": _hours(activity.get("offsite")),
            "totalJobHours": round(total_job_hours, 2),
            "loadedLaborRate": loaded_labor_rate,
            "laborCost": labor_cost,
        },
        "items": {
            "knownItemCost": round(item_cost, 2),
            "missingCostItems": missing_cost_items,
        },
        "profitability": {
            "knownCost": known_cost,
            "grossProfit": gross_profit,
            "grossMarginPct": gross_margin,
        },
        "warnings": [
            "Gross margin is provisional when job-item costs are zero/null or invoices are not issued.",
            "Loaded labor rate should include direct wage plus payroll burden; overhead should be analyzed separately unless intentionally allocated.",
        ],
    }
