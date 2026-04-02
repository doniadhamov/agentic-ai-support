"""Groups management page — manage Telegram groups via the database."""

from __future__ import annotations

import streamlit as st

from src.admin.dashboard.styles import SHARED_CSS, sidebar_branding
from src.admin.dashboard.utils import run_async
from src.database.repositories import (
    add_telegram_group,
    get_all_telegram_groups,
    get_group_message_counts_today,
    get_open_tickets_by_group,
    remove_telegram_group,
    set_group_active,
)

st.set_page_config(page_title="Groups — DataTruck Admin", layout="wide")
st.markdown(SHARED_CSS, unsafe_allow_html=True)

st.title("👥 Telegram Groups")
st.caption("Manage which Telegram groups the bot monitors and responds in.")

# --- Load data ---
groups = run_async(get_all_telegram_groups())
active_groups = [g for g in groups if g.active]
msg_counts = run_async(get_group_message_counts_today())
ticket_counts = run_async(get_open_tickets_by_group())

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
            help="Telegram group chat ID (negative number for groups/supergroups).",
        )
    with col2:
        group_name = st.text_input("Display Name", placeholder="e.g. DataTruck Support RU")
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("Add Group", type="primary", use_container_width=True)

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
        "Search groups",
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
        # Table header
        hdr = st.columns([2, 3, 1, 1, 1, 1, 1])
        headers = ["Group ID", "Name", "Msgs Today", "Open Tickets", "Status", "Created", "Actions"]
        for h, label in zip(hdr, headers, strict=True):
            with h:
                st.markdown(f"**{label}**")

        for group in filtered:
            c = st.columns([2, 3, 1, 1, 1, 1, 1])
            chat_id = group.telegram_chat_id
            with c[0]:
                st.code(str(chat_id), language=None)
            with c[1]:
                st.markdown(f"**{group.title}**" if group.title else "*Unnamed*")
            with c[2]:
                count = msg_counts.get(chat_id, 0)
                st.markdown(f"**{count}**" if count > 0 else "0")
            with c[3]:
                tickets = ticket_counts.get(chat_id, 0)
                if tickets > 0:
                    st.markdown(
                        f'<span class="status-badge status-open">{tickets}</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown("0")
            with c[4]:
                st.markdown("🟢 Active" if group.active else "🔴 Inactive")
            with c[5]:
                st.caption(group.created_at.strftime("%b %d, %Y") if group.created_at else "—")
            with c[6]:
                btn_c1, btn_c2 = st.columns(2)
                with btn_c1:
                    toggle_label = "⏸️" if group.active else "▶️"
                    toggle_help = "Deactivate" if group.active else "Activate"
                    if st.button(toggle_label, key=f"toggle_{chat_id}", help=toggle_help):
                        run_async(set_group_active(chat_id, not group.active))
                        st.rerun()
                with btn_c2:
                    if st.button("🗑️", key=f"del_{chat_id}", help="Remove group"):
                        run_async(remove_telegram_group(chat_id))
                        st.rerun()

    st.caption(f"Showing {len(filtered)} of {len(groups)} group(s)")


sidebar_branding()
