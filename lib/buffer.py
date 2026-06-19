"""Buffer API client — schedule posts with videos to YouTube + Instagram."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

API_URL = "https://api.buffer.com"


def _headers():
    key = os.environ.get("BUFFER_API_KEY")
    if not key:
        raise RuntimeError("BUFFER_API_KEY not set in .env")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }


def _graphql(query: str, variables: dict | None = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(API_URL, headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_organizations() -> list[dict]:
    """Return [{id, name}, ...] for all organizations."""
    data = _graphql("""
        query GetOrganizations {
            account {
                organizations {
                    id
                    name
                }
            }
        }
    """)
    return data.get("data", {}).get("account", {}).get("organizations", [])


def get_channels(org_id: str) -> list[dict]:
    """Return [{id, name, service}, ...] for all channels in an organization."""
    data = _graphql("""
        query GetChannels($orgId: ID!) {
            channels(input: { organizationId: $orgId }) {
                id
                name
                service
            }
        }
    """, {"orgId": org_id})
    return data.get("data", {}).get("channels", [])


def find_channels(org_id: str | None = None, services: list[str] | None = None) -> list[dict]:
    """Find channels, optionally filtered by service name (e.g. ["youtube", "instagram"])."""
    if not org_id:
        orgs = get_organizations()
        if not orgs:
            raise RuntimeError("No Buffer organizations found")
        org_id = orgs[0]["id"]
    channels = get_channels(org_id)
    if services:
        channels = [c for c in channels if c.get("service") in services]
    return channels


def schedule_post(
    channel_id: str,
    text: str,
    video_url: str,
    due_at: datetime | None = None,
    thumbnail_url: str | None = None,
) -> dict:
    """Schedule a post with a video to a specific channel.

    Args:
        channel_id: Buffer channel ID
        text: Post text/caption
        video_url: Public URL of the video (from Cloudinary)
        due_at: When to publish (UTC). Defaults to 1 minute from now.
        thumbnail_url: Optional public URL for video thumbnail.

    Returns: {"id": str, "text": str, "dueAt": str} on success, or error dict.
    """
    if due_at is None:
        due_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    due_at_str = due_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    assets = [{"video": {"url": video_url}}]
    if thumbnail_url:
        assets[0]["video"]["thumbnailUrl"] = thumbnail_url

    mutation = """
        mutation SchedulePost($input: CreatePostInput!) {
            createPost(input: $input) {
                ... on PostActionSuccess {
                    post {
                        id
                        text
                        dueAt
                    }
                }
                ... on MutationError {
                    message
                }
            }
        }
    """
    variables = {
        "input": {
            "text": text,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "customScheduled",
            "dueAt": due_at_str,
            "assets": assets,
        }
    }
    data = _graphql(mutation, variables)
    result = data.get("data", {}).get("createPost", {})
    if "post" in result:
        return {"status": "scheduled", **result["post"]}
    return {"status": "error", "message": result.get("message", "Unknown error")}


def schedule_to_youtube_and_instagram(
    video_url: str,
    text: str,
    due_at: datetime | None = None,
    services: list[str] | None = None,
) -> list[dict]:
    """Schedule a video post to YouTube and Instagram channels.

    Returns: list of results per channel.
    """
    if services is None:
        services = ["youtube", "instagram"]
    channels = find_channels(services=services)
    if not channels:
        raise RuntimeError(f"No Buffer channels found for services: {services}")

    results = []
    for ch in channels:
        result = schedule_post(
            channel_id=ch["id"],
            text=text,
            video_url=video_url,
            due_at=due_at,
        )
        result["channel"] = ch.get("name", ch["id"])
        result["service"] = ch.get("service")
        results.append(result)
    return results


def smoke_test() -> dict:
    """Verify Buffer API credentials and list channels."""
    try:
        orgs = get_organizations()
        if not orgs:
            return {"status": "error", "message": "No organizations found"}
        org_id = orgs[0]["id"]
        channels = get_channels(org_id)
        return {
            "status": "ok",
            "organization": orgs[0]["name"],
            "channels": [
                {"id": c["id"], "name": c["name"], "service": c["service"]}
                for c in channels
            ],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def smoke_test_direct() -> dict:
    """Direct test without going through the GraphQL wrapper."""
    try:
        resp = requests.post(
            API_URL,
            headers=_headers(),
            json={"query": "{ account { organizations { id name } } }"},
            timeout=30,
        )
        resp.raise_for_status()
        orgs = resp.json().get("data", {}).get("account", {}).get("organizations", [])
        if not orgs:
            return {"status": "error", "message": "No organizations found"}
        org_id = orgs[0]["id"]
        resp2 = requests.post(
            API_URL,
            headers=_headers(),
            json={"query": f'{{ channels(input: {{ organizationId: "{org_id}" }}) {{ id name service }} }}'},
            timeout=30,
        )
        resp2.raise_for_status()
        channels = resp2.json().get("data", {}).get("channels", [])
        return {
            "status": "ok",
            "organization": orgs[0]["name"],
            "channels": [
                {"id": c["id"], "name": c["name"], "service": c["service"]}
                for c in channels
            ],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
