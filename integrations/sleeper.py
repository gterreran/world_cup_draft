from __future__ import annotations

import requests

BASE_URL = "https://api.sleeper.app/v1"


class SleeperAPIError(RuntimeError):
    pass


def _get(path: str) -> dict | list:
    response = requests.get(f"{BASE_URL}{path}", timeout=15)
    if response.status_code >= 400:
        raise SleeperAPIError(f"Sleeper API returned {response.status_code}: {response.text}")
    return response.json()


def get_league(league_id: str) -> dict:
    return _get(f"/league/{league_id}")


def get_users(league_id: str) -> list[dict]:
    data = _get(f"/league/{league_id}/users")
    return data if isinstance(data, list) else []


def get_rosters(league_id: str) -> list[dict]:
    data = _get(f"/league/{league_id}/rosters")
    return data if isinstance(data, list) else []
