import os
import json
import hmac
import hashlib
import httpx
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta, timezone

app = FastAPI(title="Human Pages for Omi", version="1.0.0")

HP_BASE = os.environ.get("HP_BASE_URL", "https://humanpages.ai/api")
HP_AGENT_KEY = os.environ.get("HP_AGENT_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OMI_APP_ID = os.environ.get("OMI_APP_ID", "")
OMI_APP_SECRET = os.environ.get("OMI_APP_SECRET", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


# --- Helpers ---

async def hp_request(method: str, path: str, **kwargs) -> dict:
    headers = kwargs.pop("headers", {})
    if HP_AGENT_KEY:
        headers["X-Agent-Key"] = HP_AGENT_KEY
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.request(method, f"{HP_BASE}{path}", headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json()


async def llm_extract_service_need(transcript: str) -> dict | None:
    """Ask an LLM whether the conversation contains a service need.
    Returns {"title", "description", "skills", "budget"} or None."""
    if not OPENAI_API_KEY:
        return None

    prompt = (
        "You analyze conversation transcripts from an AI wearable device. "
        "Determine if the speaker explicitly expressed a need to hire someone "
        "or find a service provider for a task. Only flag clear, actionable needs "
        "— not vague wishes or hypotheticals.\n\n"
        "If a service need is found, respond with JSON:\n"
        '{"need": true, "title": "short title", "description": "what they need done", '
        '"skills": ["skill1", "skill2"], "budget_estimate_usd": 50}\n\n'
        "If no clear service need, respond with:\n"
        '{"need": false}\n\n'
        f"Transcript:\n{transcript[:4000]}"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        return result if result.get("need") else None


def flatten_transcript(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        speaker = seg.get("speaker_name") or seg.get("speaker", "Speaker")
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


# --- Omi Webhook: memory_creation ---

@app.post("/webhook")
async def memory_webhook(request: Request, uid: str = Query("")):
    """Called by Omi when a conversation ends (memory_creation trigger)."""
    body = await request.json()

    segments = body.get("transcript_segments", [])
    if not segments:
        return {"message": ""}

    transcript = flatten_transcript(segments)
    if len(transcript) < 30:
        return {"message": ""}

    need = await llm_extract_service_need(transcript)
    if not need:
        return {"message": ""}

    # Search Human Pages for matching providers
    skills = need.get("skills", [])
    search_params = {}
    if skills:
        search_params["skill"] = skills[0]

    try:
        results = await hp_request("GET", "/humans/search", params=search_params)
        total = results.get("total", 0)
    except Exception:
        total = 0

    title = need.get("title", "Service needed")
    desc = need.get("description", "")
    budget = need.get("budget_estimate_usd", 0)

    msg = f"I detected you might need help: \"{title}\""
    if total > 0:
        msg += f"\n\nFound {total} service providers on Human Pages"
        top = results.get("results", [])[:3]
        for h in top:
            name = h.get("name", "?")
            hskills = ", ".join(h.get("skills", [])[:3]) or "various"
            msg += f"\n  - {name} ({hskills})"
        msg += "\n\nSay \"hire on Human Pages\" to post this as a job listing."
    else:
        msg += "\n\nI can post this on the Human Pages job board to find someone. Say \"hire on Human Pages\" to proceed."

    return {"message": msg}


# --- Omi Chat Tools ---

@app.get("/.well-known/omi-tools.json")
async def tools_manifest():
    return {
        "tools": [
            {
                "name": "search_service_providers",
                "description": (
                    "Search Human Pages for real humans available to hire. "
                    "Find freelancers, service providers, and gig workers by skill, "
                    "location, or budget."
                ),
                "endpoint": "/tools/search",
                "method": "POST",
                "parameters": {
                    "properties": {
                        "skill": {
                            "type": "string",
                            "description": "Skill to search for, e.g. 'photography', 'plumbing', 'web design'",
                        },
                        "location": {
                            "type": "string",
                            "description": "City or area, e.g. 'San Francisco' or 'London'",
                        },
                        "max_budget": {
                            "type": "number",
                            "description": "Maximum hourly rate in USD",
                        },
                        "work_mode": {
                            "type": "string",
                            "description": "REMOTE, ONSITE, or HYBRID",
                        },
                    },
                    "required": ["skill"],
                },
            },
            {
                "name": "post_job_listing",
                "description": (
                    "Post a job listing on the Human Pages marketplace. "
                    "Real humans can apply to do the work."
                ),
                "endpoint": "/tools/listing",
                "method": "POST",
                "parameters": {
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Job title, e.g. 'Need a photographer for Saturday event'",
                        },
                        "description": {
                            "type": "string",
                            "description": "Detailed description of what you need done",
                        },
                        "budget_usd": {
                            "type": "number",
                            "description": "Budget in USD (minimum $5)",
                        },
                        "skills": {
                            "type": "string",
                            "description": "Comma-separated required skills, e.g. 'photography,editing'",
                        },
                        "location": {
                            "type": "string",
                            "description": "Where the work should be done (or 'remote')",
                        },
                        "work_mode": {
                            "type": "string",
                            "description": "REMOTE, ONSITE, or HYBRID",
                        },
                    },
                    "required": ["title", "description", "budget_usd"],
                },
            },
            {
                "name": "hire_directly",
                "description": (
                    "Send a job offer directly to a specific person on Human Pages. "
                    "Use after searching to hire someone you found."
                ),
                "endpoint": "/tools/hire",
                "method": "POST",
                "parameters": {
                    "properties": {
                        "human_id": {
                            "type": "string",
                            "description": "The ID or username of the person to hire (from search results)",
                        },
                        "title": {
                            "type": "string",
                            "description": "Job title",
                        },
                        "description": {
                            "type": "string",
                            "description": "What you need them to do",
                        },
                        "price_usd": {
                            "type": "number",
                            "description": "How much to pay in USD",
                        },
                    },
                    "required": ["human_id", "title", "description", "price_usd"],
                },
            },
        ]
    }


@app.post("/tools/search")
async def tool_search(request: Request, uid: str = Query("")):
    body = await request.json()
    params: dict = {}
    if skill := body.get("skill"):
        params["skill"] = skill
    if location := body.get("location"):
        params["location"] = location
    if max_budget := body.get("max_budget"):
        params["maxRate"] = max_budget
    if work_mode := body.get("work_mode"):
        params["workMode"] = work_mode

    try:
        results = await hp_request("GET", "/humans/search", params=params)
    except httpx.HTTPStatusError as e:
        return {"error": f"Search failed: {e.response.status_code}"}

    total = results.get("total", 0)
    humans = results.get("results", [])[:5]

    if total == 0:
        return {"result": "No service providers found matching your criteria. Try broadening your search."}

    lines = [f"Found {total} service providers on Human Pages:\n"]
    for h in humans:
        name = h.get("name", "?")
        hid = h.get("id", "")
        username = h.get("username", "")
        skills = ", ".join(h.get("skills", [])[:4]) or "various"
        rate = h.get("minRateUsdEstimate") or h.get("minRateUsdc") or "?"
        loc = h.get("location", "")
        jobs = h.get("reputation", {}).get("jobsCompleted", 0)
        rating = h.get("reputation", {}).get("avgRating", 0)

        line = f"- {name} ({username}) | {skills} | ${rate}/hr"
        if loc:
            line += f" | {loc}"
        if jobs:
            line += f" | {jobs} jobs done"
        if rating:
            line += f" | {rating:.1f} stars"
        line += f"\n  ID: {hid}"
        lines.append(line)

    lines.append(f"\nSay \"hire [name]\" to send a job offer directly, or \"post a listing\" to let people apply.")
    return {"result": "\n".join(lines)}


@app.post("/tools/listing")
async def tool_listing(request: Request, uid: str = Query("")):
    body = await request.json()

    title = body.get("title", "")
    description = body.get("description", "")
    budget = body.get("budget_usd", 0)

    if not title or not description or budget < 5:
        return {"error": "Need a title, description, and budget of at least $5"}

    payload: dict = {
        "title": title,
        "description": description,
        "budgetUsdc": budget,
        "expiresAt": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
    }

    if skills := body.get("skills"):
        payload["requiredSkills"] = [s.strip() for s in skills.split(",")]
    if location := body.get("location"):
        payload["location"] = location
    if work_mode := body.get("work_mode"):
        payload["workMode"] = work_mode

    try:
        result = await hp_request("POST", "/listings", json=payload)
    except httpx.HTTPStatusError as e:
        error_body = e.response.text
        return {"error": f"Failed to create listing: {error_body}"}

    listing_id = result.get("id", "")
    return {
        "result": (
            f"Job listing posted on Human Pages!\n"
            f"Title: {title}\n"
            f"Budget: ${budget}\n"
            f"Listing ID: {listing_id}\n"
            f"View at: https://humanpages.ai/listings/{listing_id}\n\n"
            f"People can now apply. I'll notify you when someone does."
        )
    }


@app.post("/tools/hire")
async def tool_hire(request: Request, uid: str = Query("")):
    body = await request.json()

    human_id = body.get("human_id", "")
    title = body.get("title", "")
    description = body.get("description", "")
    price = body.get("price_usd", 0)

    if not all([human_id, title, description, price]):
        return {"error": "Need human_id, title, description, and price_usd"}

    payload = {
        "humanId": human_id,
        "title": title,
        "description": description,
        "priceUsdc": price,
        "agentId": OMI_APP_ID or "omi-humanpages",
    }

    try:
        result = await hp_request("POST", "/jobs", json=payload)
    except httpx.HTTPStatusError as e:
        error_body = e.response.text
        return {"error": f"Failed to send offer: {error_body}"}

    job_id = result.get("id", "")
    return {
        "result": (
            f"Job offer sent!\n"
            f"Title: {title}\n"
            f"Price: ${price}\n"
            f"Job ID: {job_id}\n\n"
            f"The person will be notified. I'll update you when they respond."
        )
    }


# --- Health ---

@app.get("/")
async def root():
    return {
        "name": "Human Pages for Omi",
        "description": "Hire real humans for tasks — directly from your Omi wearable",
        "version": "1.0.0",
        "docs": "https://github.com/human-pages-ai/omi-humanpages",
    }


@app.get("/setup_check")
async def setup_check(uid: str = Query("")):
    """Omi calls this to verify the plugin is configured."""
    if not HP_AGENT_KEY:
        return JSONResponse({"is_setup_completed": False, "message": "HP_AGENT_KEY not configured"})
    return JSONResponse({"is_setup_completed": True})
