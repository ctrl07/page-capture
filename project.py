"""Project management — organize runs into named projects."""

from __future__ import annotations

import json
from datetime import datetime

from runners import HERE

_PROJECTS_FILE = HERE / ".projects.json"


def _load_raw() -> list[dict]:
    if not _PROJECTS_FILE.exists():
        return []
    try:
        with _PROJECTS_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_raw(projects: list[dict]) -> None:
    _PROJECTS_FILE.write_text(json.dumps(projects, indent=2), encoding="utf-8")


def _next_id(projects: list[dict]) -> str:
    used = {p["id"] for p in projects}
    i = 1
    while str(i) in used:
        i += 1
    return str(i)


def list_projects() -> list[dict]:
    return _load_raw()


def get_project(project_id: str) -> dict | None:
    for p in _load_raw():
        if p["id"] == project_id:
            return p
    return None


def create_project(name: str, description: str = "") -> dict:
    projects = _load_raw()
    now = datetime.now().isoformat()
    project = {
        "id": _next_id(projects),
        "name": name,
        "description": description,
        "created_at": now,
        "updated_at": now,
        "run_indices": [],
    }
    projects.insert(0, project)
    _save_raw(projects)
    return project


def update_project(project_id: str, name: str | None = None, description: str | None = None) -> bool:
    projects = _load_raw()
    for p in projects:
        if p["id"] == project_id:
            if name is not None:
                p["name"] = name
            if description is not None:
                p["description"] = description
            p["updated_at"] = datetime.now().isoformat()
            _save_raw(projects)
            return True
    return False


def delete_project(project_id: str) -> bool:
    projects = _load_raw()
    new_projects = [p for p in projects if p["id"] != project_id]
    if len(new_projects) == len(projects):
        return False
    _save_raw(new_projects)
    return True


def add_run_to_project(project_id: str, run_index: int) -> bool:
    projects = _load_raw()
    for p in projects:
        if p["id"] == project_id:
            if run_index not in p["run_indices"]:
                p["run_indices"].append(run_index)
                p["updated_at"] = datetime.now().isoformat()
                _save_raw(projects)
            return True
    return False


def remove_run_from_project(project_id: str, run_index: int) -> bool:
    projects = _load_raw()
    for p in projects:
        if p["id"] == project_id:
            if run_index in p["run_indices"]:
                p["run_indices"].remove(run_index)
                p["updated_at"] = datetime.now().isoformat()
                _save_raw(projects)
            return True
    return False


def get_runs_for_project(project_id: str, history: list[dict]) -> list[dict]:
    from runners import load_history

    history = load_history()
    project = get_project(project_id)
    if not project:
        return []
    return [history[i] for i in project["run_indices"] if 0 <= i < len(history)]
