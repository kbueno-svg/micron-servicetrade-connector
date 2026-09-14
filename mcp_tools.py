from typing import Any, Callable, Optional


def register_tools(mcp, st_get: Callable[..., Any], labor_summary: Callable[..., Any], profitability: Callable[..., Any]):
    @mcp.tool(description="Identify the ServiceTrade account connected to this Micron connector.")
    async def service_trade_identity() -> dict:
        return await st_get("/oauth2/userinfo")

    @mcp.tool(description="Search Micron ServiceTrade jobs. Use status when the user asks for open, completed, scheduled, or similar job states.")
    async def search_jobs(limit: int = 20, page: int = 1, status: Optional[str] = None) -> dict:
        limit = max(1, min(limit, 100))
        page = max(1, page)
        params = {"limit": limit, "page": page}
        if status:
            params["status"] = status
        return await st_get("/job", params=params)

    @mcp.tool(description="Get the full ServiceTrade record for one job by ServiceTrade job ID.")
    async def get_job(job_id: int) -> dict:
        return await st_get(f"/job/{job_id}")

    @mcp.tool(description="Get job items, quantities, and captured costs for one ServiceTrade job.")
    async def get_job_items(job_id: int) -> dict:
        return await st_get("/jobitem", params={"jobId": job_id})

    @mcp.tool(description="Get invoices associated with one ServiceTrade job.")
    async def get_job_invoices(job_id: int) -> dict:
        return await st_get("/invoice", params={"jobId": job_id})

    @mcp.tool(description="Summarize actual technician labor for a job, including onsite, en route, offsite, break, and per-technician hours.")
    async def get_job_labor(job_id: int) -> dict:
        return await labor_summary(job_id)

    @mcp.tool(description="Calculate provisional job profitability from ServiceTrade revenue, captured item costs, and actual job labor. loaded_labor_rate should include direct wage plus payroll burden when supplied.")
    async def get_job_profitability(job_id: int, loaded_labor_rate: Optional[float] = None) -> dict:
        if loaded_labor_rate is not None and loaded_labor_rate < 0:
            raise ValueError("loaded_labor_rate must be nonnegative")
        return await profitability(job_id, loaded_labor_rate)
