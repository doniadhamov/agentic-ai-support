"""Groups management page — manage the Telegram group allowlist."""

from __future__ import annotations

import streamlit as st

from src.admin.group_store import GroupStore

st.set_page_config(page_title="Groups — DataTruck Admin", layout="wide")
st.title("Telegram Group Allowlist")


@st.cache_resource
def _get_store() -> GroupStore:
    return GroupStore()


store = _get_store()

# --- Status indicator ---
groups = store.list_groups()
if groups:
    st.success(f"Allowlist **ACTIVE** — {len(groups)} group(s) registered")
else:
    st.warning("Allowlist **INACTIVE** — bot accepts messages from all groups")

# --- Add group form ---
st.subheader("Add Group")
with st.form("add_group", clear_on_submit=True):
    col1, col2 = st.columns([1, 2])
    with col1:
        group_id = st.number_input(
            "Group ID",
            value=0,
            step=1,
            format="%d",
            help="Telegram group chat ID (negative number for groups/supergroups)",
        )
    with col2:
        group_name = st.text_input(
            "Display Name",
            placeholder="e.g. DataTruck Support RU",
        )
    submitted = st.form_submit_button("Add Group")
    if submitted:
        if group_id == 0:
            st.error("Group ID cannot be zero")
        else:
            store.add_group(int(group_id), group_name)
            st.success(f"Added group {group_id}")
            st.rerun()

# --- Groups table ---
st.subheader("Current Groups")
if not groups:
    st.info("No groups in allowlist. The bot will respond to all groups.")
else:
    for group in groups:
        col1, col2, col3, col4 = st.columns([2, 3, 3, 1])
        with col1:
            st.code(str(group.group_id))
        with col2:
            st.write(group.name or "—")
        with col3:
            st.write(group.added_at.strftime("%Y-%m-%d %H:%M UTC"))
        with col4:
            if st.button("Delete", key=f"del_{group.group_id}"):
                store.remove_group(group.group_id)
                st.rerun()
