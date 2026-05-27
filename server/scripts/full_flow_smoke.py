"""End-to-end smoke test for the comic Agent pipeline.

This script calls the running FastAPI server, then verifies:
1. Agent script generation.
2. Script-to-storyboard generation with reference images.
3. Manual storyboard edit.
4. Storyboard confirmation and final video composition.

Usage:
    python scripts/full_flow_smoke.py
    API_BASE=http://127.0.0.1:8011 python scripts/full_flow_smoke.py
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import requests


API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8011").rstrip("/")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "output" / "projects"


def post(path: str, payload: dict | None = None) -> dict:
    response = requests.post(f"{API_BASE}{path}", json=payload or {}, timeout=30)
    response.raise_for_status()
    return response.json()


def get(path: str) -> dict | list:
    response = requests.get(f"{API_BASE}{path}", timeout=30)
    response.raise_for_status()
    return response.json()


def put(path: str, payload: dict) -> dict:
    response = requests.put(f"{API_BASE}{path}", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def wait_for(predicate, timeout: int, label: str):
    deadline = time.time() + timeout
    last_value = None
    while time.time() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(1)
    raise TimeoutError(f"{label} timed out; last value: {last_value!r}")


def main() -> None:
    health = get("/health")
    assert health.get("status") == "ok", health

    project = post(
        "/api/project",
        {
            "title": "全链路冒烟测试",
            "style": "anime",
            "genre": "测试",
            "resolution": "720p",
            "output_format": "9:16",
            "platform": "douyin",
        },
    )
    project_id = project["id"]
    print(f"PROJECT {project_id}")

    generated = post(
        "/api/script/generate",
        {
            "project_id": project_id,
            "prompt": "一个年轻创作者把灵感做成漫剧成片的温暖故事",
            "style": "anime",
            "genre": "原创短剧",
            "target_duration": 20,
        },
    )
    script = generated["script"]
    assert len(script.strip()) > 80, "script is too short"
    print(f"SCRIPT {len(script)} chars")

    parse_result = post(
        "/api/script/parse",
        {
            "project_id": project_id,
            "user_input": script,
            "style": "anime",
            "output_format": "9:16",
            "resolution": "720p",
            "platform": "douyin",
            "target_duration": 20,
        },
    )
    assert parse_result["status"] == "started", parse_result

    def storyboard_ready():
        shots = get(f"/api/shot/{project_id}/shots")
        if shots and all(shot.get("image_path") for shot in shots):
            return shots
        return None

    shots = wait_for(storyboard_ready, timeout=90, label="storyboard generation")
    assert len(shots) >= 1, "no shots generated"
    print(f"STORYBOARD {len(shots)} shots")

    first_shot = shots[0]
    edit_result = put(
        f"/api/shot/{first_shot['id']}",
        {
            "duration": 1.0,
            "dialogue": (first_shot.get("dialogue") or "我看见故事成形了") + "，这句来自冒烟测试。",
        },
    )
    assert edit_result["needs_render"] is True, edit_result
    print("EDIT ok")

    confirm_result = post(f"/api/shot/{project_id}/confirm-storyboard")
    assert confirm_result["status"] == "phase2_started", confirm_result
    print("CONFIRM ok")

    final_video = OUTPUT_ROOT / project_id / "output" / "final.mp4"

    def video_ready():
        status = get(f"/api/project/{project_id}").get("status")
        if status == "error":
            raise RuntimeError("project entered error state")
        if final_video.exists() and final_video.stat().st_size > 0 and status == "completed":
            return {"status": status, "size": final_video.stat().st_size}
        return None

    video_state = wait_for(video_ready, timeout=150, label="final video generation")
    print(f"VIDEO {final_video} {video_state['size']} bytes")
    print("FULL_FLOW_OK")


if __name__ == "__main__":
    main()
