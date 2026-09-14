# Micron ServiceTrade Connector

Read-only API wrapper for Micron Air & Mechanical Solutions ServiceTrade data.

## Purpose

This service keeps ServiceTrade OAuth credentials out of ChatGPT and exposes a small set of read-only endpoints tailored for operations and CFO analysis.

## Environment variables

- `SERVICETRADE_BASE_URL=https://api.servicetrade.com/api`
- `SERVICETRADE_CLIENT_ID` (secret)
- `SERVICETRADE_CLIENT_SECRET` (secret)
- `CONNECTOR_API_KEY` (reserved for connector-level authentication)

Never commit secrets to Git or upload them to Drive.

## Endpoints

- `GET /health`
- `GET /whoami`
- `GET /jobs?limit=20&page=1`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/items`
- `GET /jobs/{job_id}/invoices`
- `GET /jobs/{job_id}/clock`
- `GET /jobs/{job_id}/labor-summary`
- `GET /jobs/{job_id}/profitability?loaded_labor_rate=...`

## ECTC test job

ServiceTrade job id: `2715694029190401`

Expected labor summary from current data:
- onsite: 47.63 h
- enroute: 8.72 h
- total job-associated time: 56.35 h

## Deployment

Deploy using `render.yaml` on Render. Enter the ServiceTrade client ID and secret directly in Render's secret environment-variable UI.
