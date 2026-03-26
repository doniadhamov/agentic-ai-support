"""Groups management page — manage Telegram groups via the database."""

from __future__ import annotations

import streamlit as st

from src.admin.dashboard.utils import run_async
from src.database.repositories import (
    add_telegram_group,
    get_all_telegram_groups,
    remove_telegram_group,
    set_group_active,
)

st.set_page_config(page_title="Groups — DataTruck Admin", layout="wide")

# --- Custom CSS ---
st.markdown(
    """
<style>
div[data-testid="stMetric"] {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 12px;
    padding: 20px 24px;
    color: white !important;
    box-shadow: 0 4px 15px rgba(102,126,234,0.3);
}
div[data-testid="stMetric"] label { color: rgba(255,255,255,0.85) !important; font-weight: 500 !important; text-transform: uppercase; letter-spacing: 0.5px; }
div[data-testid="stMetric"] [data-testid="stMetricValue"] { color: white !important; font-size: 2rem !important; font-weight: 700 !important; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%); }
section[data-testid="stSidebar"] .stMarkdown p, section[data-testid="stSidebar"] .stMarkdown a, section[data-testid="stSidebar"] span { color: #e0e0e0 !important; }
</style>
""",
    unsafe_allow_html=True,
)

# --- Page header ---
st.title("👥 Telegram Groups")
st.caption("Manage which Telegram groups the bot monitors and responds in.")

# --- Load groups from DB ---
groups = run_async(get_all_telegram_groups())
active_groups = [g for g in groups if g.active]

# --- Status metrics ---
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Groups", len(groups))
with col2:
    st.metric("Active Groups", len(active_groups))
with col3:
    st.metric("Mode", "Allowlist" if active_groups else "All Groups")

st.markdown("")

if active_groups:
    st.success(
        f"Allowlist is **active** — the bot only responds in **{len(active_groups)}** active group(s)."
    )
else:
    st.warning(
        "No active groups — the bot currently accepts messages from **all** groups. "
        "Add a group below to activate the allowlist."
    )

# --- Add group form ---
st.markdown("#### Add New Group")
with st.form("add_group", clear_on_submit=True):
    col1, col2, col3 = st.columns([2, 3, 1])
    with col1:
        group_id = st.number_input(
            "Group ID",
            value=0,
            step=1,
            format="%d",
            help="Telegram group chat ID (negative number for groups/supergroups). "
            "You can get this from the bot logs or using @userinfobot.",
        )
    with col2:
        group_name = st.text_input(
            "Display Name",
            placeholder="e.g. DataTruck Support RU",
        )
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("➕ Add Group", type="primary", use_container_width=True)

    if submitted:
        if group_id == 0:
            st.error("Group ID cannot be zero.")
        else:
            run_async(add_telegram_group(int(group_id), title=group_name or None))
            st.success(f"Added group **{group_name or group_id}**")
            st.rerun()

st.divider()

# --- Groups table ---
st.markdown("#### Registered Groups")
if not groups:
    st.info("No groups registered yet. The bot will respond to messages from all groups.")
else:
    search = st.text_input(
        "🔍 Search groups",
        placeholder="Filter by name or ID...",
        label_visibility="collapsed",
    )

    filtered = groups
    if search:
        search_lower = search.lower()
        filtered = [
            g
            for g in groups
            if search_lower in (g.title or "").lower() or search_lower in str(g.telegram_chat_id)
        ]

    if not filtered:
        st.warning("No groups match your search.")
    else:
        hdr1, hdr2, hdr3, hdr4, hdr5 = st.columns([2, 3, 2, 1, 1])
        with hdr1:
            st.markdown("**Group ID**")
        with hdr2:
            st.markdown("**Name**")
        with hdr3:
            st.markdown("**Created**")
        with hdr4:
            st.markdown("**Status**")
        with hdr5:
            st.markdown("**Action**")

        for group in filtered:
            c1, c2, c3, c4, c5 = st.columns([2, 3, 2, 1, 1])
            with c1:
                st.code(str(group.telegram_chat_id), language=None)
            with c2:
                st.markdown(f"**{group.title}**" if group.title else "*Unnamed*")
            with c3:
                st.caption(group.created_at.strftime("%b %d, %Y  %H:%M UTC"))
            with c4:
                if group.active:
                    st.markdown("🟢 Active")
                else:
                    st.markdown("🔴 Inactive")
            with c5:
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    toggle_label = "⏸️" if group.active else "▶️"
                    toggle_help = "Deactivate" if group.active else "Activate"
                    if st.button(
                        toggle_label, key=f"toggle_{group.telegram_chat_id}", help=toggle_help
                    ):
                        run_async(set_group_active(group.telegram_chat_id, not group.active))
                        st.rerun()
                with btn_col2:
                    if st.button("🗑️", key=f"del_{group.telegram_chat_id}", help="Remove group"):
                        run_async(remove_telegram_group(group.telegram_chat_id))
                        st.rerun()

    st.caption(f"Showing {len(filtered)} of {len(groups)} group(s)")

# --- Sidebar ---
with st.sidebar:
    st.markdown("---")
    st.markdown("**DataTruck Admin** v1.0\n\nAI-powered support bot management console.")
