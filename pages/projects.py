"""Project management — create, edit, delete projects and associate runs."""

from __future__ import annotations

import streamlit as st

from project import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    remove_run_from_project,
    update_project,
)
from runners import load_history


def _render_project_card(project: dict) -> None:
    with st.container(border=True):
        c1, c2 = st.columns([4, 1])
        with c1:
            st.markdown(f"**{project['name']}**")
            if project.get("description"):
                st.caption(project["description"])
            st.caption(f"{len(project['run_indices'])} runs | Created {project['created_at'][:10]}")
        with c2:
            with st.popover("Actions", key=f"proj_act_{project['id']}"):
                if st.button("Edit", key=f"proj_edit_{project['id']}", use_container_width=True):
                    st.session_state["_edit_project_id"] = project["id"]
                    st.rerun()
                if st.button("Delete", key=f"proj_del_{project['id']}", use_container_width=True, type="secondary"):
                    st.session_state["_delete_project_id"] = project["id"]
                    st.rerun()

        history = load_history()
        run_indices = project.get("run_indices", [])
        if run_indices:
            with st.expander(f"Associated Runs ({len(run_indices)})", expanded=False):
                for idx in run_indices:
                    if 0 <= idx < len(history):
                        entry = history[idx]
                        kind = entry.get("kind", "?")
                        ts = entry.get("timestamp", "")[:19]
                        total = entry.get("total", 0)
                        ok = entry.get("ok", 0)
                        st.text(f"[{ts}] {kind} — {total} URLs, {ok} OK")
                        if st.button("Remove", key=f"proj_rm_{project['id']}_{idx}"):
                            remove_run_from_project(project["id"], idx)
                            st.rerun()


def _render_create_form() -> None:
    with st.container(border=True):
        st.markdown("### New Project")
        name = st.text_input("Project name", key="proj_new_name")
        desc = st.text_area("Description (optional)", key="proj_new_desc", height=68)
        if st.button("Create", key="proj_new_create", type="primary", disabled=not name.strip()):
            p = create_project(name.strip(), desc.strip())
            st.success(f"Project '{p['name']}' created.")
            st.rerun()


def _render_edit_form(project_id: str) -> None:
    project = get_project(project_id)
    if not project:
        st.session_state.pop("_edit_project_id", None)
        st.rerun()
        return

    with st.container(border=True):
        st.markdown(f"### Edit Project — {project['name']}")
        name = st.text_input("Project name", value=project["name"], key="proj_edit_name")
        desc = st.text_area("Description", value=project.get("description", ""), key="proj_edit_desc", height=68)
        c1, c2 = st.columns([1, 4])
        with c1:
            if st.button("Save", key="proj_edit_save", type="primary"):
                update_project(project_id, name=name.strip(), description=desc.strip())
                st.session_state.pop("_edit_project_id", None)
                st.rerun()
        with c2:
            if st.button("Cancel", key="proj_edit_cancel"):
                st.session_state.pop("_edit_project_id", None)
                st.rerun()


def _render_delete_confirm(project_id: str) -> None:
    project = get_project(project_id)
    if not project:
        st.session_state.pop("_delete_project_id", None)
        st.rerun()
        return

    st.warning(f"Delete project **'{project['name']}'**? Runs will not be deleted.")
    c1, c2 = st.columns([1, 4])
    with c1:
        if st.button("Yes, delete", key="proj_del_yes", type="primary"):
            delete_project(project_id)
            st.session_state.pop("_delete_project_id", None)
            st.rerun()
    with c2:
        if st.button("Cancel", key="proj_del_no"):
            st.session_state.pop("_delete_project_id", None)
            st.rerun()


def page_projects() -> None:
    st.subheader("Projects")

    edit_id = st.session_state.get("_edit_project_id")
    delete_id = st.session_state.get("_delete_project_id")

    if edit_id:
        _render_edit_form(edit_id)
        return

    if delete_id:
        _render_delete_confirm(delete_id)
        return

    _render_create_form()

    st.markdown("---")

    projects = list_projects()
    if not projects:
        st.info("No projects yet. Create one above to organize your runs.")
        return

    for project in projects:
        _render_project_card(project)
