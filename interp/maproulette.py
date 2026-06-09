"""Stage 3: create the MapRoulette challenge and upload the tasks.

Requires the MAPROULETTE_API_KEY environment variable and a real
maproulette.project_id in config.toml. Mirrors the auth/validation approach of
the sibling bikeshare tool, but uploads tasks in batches (one challenge here can
hold tens of thousands of lines, so per-task PUTs would take hours).
"""
import os
import time

import requests


class MaprouletteError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("MAPROULETTE_API_KEY")
    if not key:
        raise MaprouletteError(
            "MAPROULETTE_API_KEY environment variable is not set."
        )
    return key


def _session(api_key: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"apiKey": api_key, "User-Agent": "against-interpolation"})
    return s


def validate_project(api_base: str, project_id: int) -> str:
    """Return the project name, or raise if it isn't accessible."""
    s = _session(_api_key())
    resp = s.get(f"{api_base}/project/{project_id}", timeout=60)
    if resp.status_code == 404:
        raise MaprouletteError(f"MapRoulette project {project_id} not found.")
    if resp.status_code == 401:
        raise MaprouletteError(
            f"Unauthorized for project {project_id}; check MAPROULETTE_API_KEY."
        )
    resp.raise_for_status()
    return resp.json().get("name", f"project {project_id}")


def create_challenge(
    api_base: str, project_id: int, name: str, instruction: str
) -> int:
    """Create an empty challenge under the project; return its id."""
    s = _session(_api_key())
    payload = {
        "name": name,
        "description": name,
        "instruction": instruction,
        "blurb": "Retire redundant addr:interpolation lines in Toronto.",
        "checkinComment": "Removed redundant addr:interpolation line (Toronto Open Data points)",
        "enabled": True,
        "difficulty": 2,
        "requiresLocal": False,
        "parent": project_id,
    }
    resp = s.post(f"{api_base}/challenge", json=payload, timeout=120)
    if not resp.ok:
        raise MaprouletteError(
            f"Failed to create challenge ({resp.status_code}): {resp.text}"
        )
    return resp.json()["id"]


def add_tasks(
    api_base: str,
    challenge_id: int,
    task_lines: list[str],
    batch_size: int,
    delay_s: float = 0.5,
) -> None:
    """Upload RS/newline-delimited task lines to a challenge in batches."""
    s = _session(_api_key())
    url = f"{api_base}/challenge/{challenge_id}/addTasks"
    total = len(task_lines)
    for start in range(0, total, batch_size):
        batch = task_lines[start : start + batch_size]
        body = "\n".join(batch)
        resp = s.put(
            url,
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=300,
        )
        if not resp.ok:
            raise MaprouletteError(
                f"addTasks failed at {start}-{start + len(batch)} "
                f"({resp.status_code}): {resp.text}"
            )
        print(f"  uploaded {min(start + len(batch), total)}/{total} tasks")
        if start + batch_size < total:
            time.sleep(delay_s)
