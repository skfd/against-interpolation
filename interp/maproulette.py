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


def _request_with_retry(method, *args, retries: int = 4, **kwargs):
    """Issue a request, retrying transient network timeouts with backoff.

    MapRoulette occasionally takes longer than the read timeout on a single
    addTasks PUT; a lone timeout shouldn't abort an upload of dozens of
    challenges. Only the connection-level timeouts/errors are retried — an HTTP
    error response is returned to the caller to handle.
    """
    transient = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
    for attempt in range(1, retries + 1):
        try:
            return method(*args, **kwargs)
        except transient as e:
            if attempt == retries:
                raise
            wait = 2 ** attempt
            print(f"  transient network error ({type(e).__name__}); "
                  f"retry {attempt}/{retries - 1} in {wait}s...")
            time.sleep(wait)


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
        "checkinComment": "Removed redundant addr:interpolation line (Toronto Open Data points) #maproulette #toronto-interpolation-cleanup",
        "enabled": True,
        "difficulty": 3,  # 1=easy, 2=normal, 3=expert
        "requiresLocal": True,  # requires local / specialized knowledge
        "parent": project_id,
    }
    resp = _request_with_retry(
        s.post, f"{api_base}/challenge", json=payload, timeout=120
    )
    if not resp.ok:
        raise MaprouletteError(
            f"Failed to create challenge ({resp.status_code}): {resp.text}"
        )
    return resp.json()["id"]


def add_tasks(
    api_base: str,
    challenge_id: int,
    task_lines: list[str],
    delay_s: float = 0.1,
) -> None:
    """Upload tasks one FeatureCollection per request.

    MapRoulette's addTasks endpoint parses a single JSON value per PUT, so the
    U+001E record-separator prefix (and concatenating multiple FeatureCollections
    in one body) is rejected. We strip the RS and PUT each line individually,
    matching the proven sibling bikeshare tool.
    """
    s = _session(_api_key())
    url = f"{api_base}/challenge/{challenge_id}/addTasks"
    total = len(task_lines)
    ok = 0
    for i, line in enumerate(task_lines, 1):
        body = line.lstrip(chr(0x1e)).strip()  # drop U+001E record separator
        if not body:
            continue
        resp = _request_with_retry(
            s.put,
            url,
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
        if not resp.ok:
            raise MaprouletteError(
                f"addTasks failed on task {i}/{total} "
                f"({resp.status_code}): {resp.text}"
            )
        ok += 1
        if i % 50 == 0 or i == total:
            print(f"  uploaded {i}/{total} tasks")
        time.sleep(delay_s)
    print(f"  done: {ok}/{total} tasks created")
