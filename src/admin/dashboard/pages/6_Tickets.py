"""Tickets page — view conversation threads and Zendesk tickets."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.admin.dashboard.styles import SHARED_CSS, sidebar_branding
from src.admin.dashboard.utils import run_async

st.set_page_config(page_title="Tickets — DataTruck Admin", layout="wide")
st.markdown(SHARED_CSS, unsafe_allow_html=True)

st.title("🎫 Conversation Threads")
st.caption("View Telegram ↔ Zendesk conversation threads.")


def _load_threads() -> list[dict]:
    """Load conversation threads from the database."""
    try:
        from sqlalchemy import select

        from src.database.engine import get_engine, get_session_factory
        from src.database.models import ConversationThread

        get_engine()
        factory = get_session_factory()

        async def _fetch() -> list[dict]:
            async with factory() as session:
                stmt = select(ConversationThread).order_by(
                    ConversationThread.last_message_at.desc()
                )
                result = await session.execute(stmt)
                threads = result.scalars().all()
                return [
                    {
                        "id": t.id,
                        "group_id": t.group_id,
                        "user_id": t.user_id,
                        "zendesk_ticket_id": t.zendesk_ticket_id,
                        "subject": t.subject,
                        "status": t.status,
                        "urgency": t.urgency,
                        "created_at": str(t.created_at)[:19] if t.created_at else "—",
                        "closed_at": str(t.closed_at)[:19] if t.closed_at else "—",
                        "last_message_at": str(t.last_message_at)[:19]
                        if t.last_message_at
                        else "—",
                    }
                    for t in threads
                ]

        return run_async(_fetch())
    except Exception as exc:
        st.error(f"Failed to load threads: {exc}")
        return []


threads = _load_threads()

if not threads:
    st.info("No conversation threads yet. Threads appear as messages are synced to Zendesk.")
    sidebar_branding()
    st.stop()

# --- Status counts ---
status_counts: dict[str, int] = {}
for t in threads:
    s = t.get("status", "unknown")
    status_counts[s] = status_counts.get(s, 0) + 1

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Total Threads", len(threads))
with c2:
    st.metric("Open", status_counts.get("open", 0))
with c3:
    st.metric("Pending", status_counts.get("pending", 0))
with c4:
    st.metric("Solved/Closed", status_counts.get("solved", 0) + status_counts.get("closed", 0))

st.markdown("")

# --- Filters ---
filter_col1, filter_col2 = st.columns([1, 4])
with filter_col1:
    all_statuses = sorted({t.get("status", "unknown") for t in threads})
    selected_status = st.selectbox("Status", ["All"] + all_statuses, label_visibility="collapsed")
with filter_col2:
    search_query = st.text_input(
        "Search", placeholder="Search by subject...", label_visibility="collapsed"
    )

# --- Build filtered rows ---
zendesk_subdomain = "support.datatruck.io"
try:
    from src.config.settings import get_settings

    _settings = get_settings()
    zendesk_subdomain = _settings.zendesk_api_subdomain or _settings.zendesk_help_center_subdomain
except Exception:
    pass

rows = []
for t in threads:
    if selected_status != "All" and t.get("status") != selected_status:
        continue
    if search_query and search_query.lower() not in (t.get("subject", "") or "").lower():
        continue

    rows.append(
        {
            "Thread ID": t.get("id", "—"),
            "Zendesk Ticket": t.get("zendesk_ticket_id", 0),
            "Subject": (t.get("subject", "") or "")[:100],
            "Status": t.get("status", "unknown"),
            "Urgency": t.get("urgency", "normal"),
            "Group": t.get("group_id", "—"),
            "User": t.get("user_id", "—"),
            "Last Message": t.get("last_message_at", "—"),
            "Created": t.get("created_at", "—"),
        }
    )

if not rows:
    st.warning("No threads match the current filters.")
else:

    def _status_icon(status: str) -> str:
        icons = {"open": "🔵", "pending": "🟡", "solved": "🟢", "closed": "⚪"}
        return icons.get(status.lower(), "⚪")

    for row in rows:
        row["Status"] = f"{_status_icon(row['Status'])} {row['Status']}"

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Thread ID": st.column_config.NumberColumn("Thread", width="small"),
            "Zendesk Ticket": st.column_config.NumberColumn("Zendesk #", width="small"),
            "Subject": st.column_config.TextColumn("Subject", width="large"),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Urgency": st.column_config.TextColumn("Urgency", width="small"),
            "Group": st.column_config.NumberColumn("Group", width="small"),
            "User": st.column_config.NumberColumn("User", width="small"),
            "Last Message": st.column_config.TextColumn("Last Msg", width="medium"),
            "Created": st.column_config.TextColumn("Created", width="medium"),
        },
    )
    st.caption(f"Showing {len(rows)} of {len(threads)} thread(s)")

    st.divider()

    # --- Detail view ---
    st.markdown("#### Thread Details")

    thread_ids = [r["Thread ID"] for r in rows]
    selected_thread_id = st.selectbox(
        "Select a thread",
        thread_ids,
        label_visibility="collapsed",
    )

    if selected_thread_id:
        thread_data = next((t for t in threads if t.get("id") == selected_thread_id), None)
        if thread_data:
            status = thread_data.get("status", "unknown").lower()
            ticket_id = thread_data.get("zendesk_ticket_id", 0)
            zendesk_link = f"https://{zendesk_subdomain}/agent/tickets/{ticket_id}"

            st.markdown(
                f"**Thread #{selected_thread_id}** &nbsp; "
                f"{_status_icon(status)} {status} &nbsp; | &nbsp; "
                f"[View in Zendesk →]({zendesk_link})"
            )

            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                st.markdown(f"**Group ID:** `{thread_data.get('group_id', '—')}`")
                st.markdown(f"**User ID:** `{thread_data.get('user_id', '—')}`")
            with mc2:
                st.markdown(f"**Zendesk Ticket:** `{ticket_id}`")
                st.markdown(f"**Urgency:** {thread_data.get('urgency', 'normal')}")
            with mc3:
                st.markdown(f"**Created:** {thread_data.get('created_at', '—')}")
                st.markdown(f"**Closed:** {thread_data.get('closed_at', '—')}")

            st.markdown("**Subject**")
            st.text_area(
                "subject_detail",
                value=thread_data.get("subject", ""),
                height=80,
                disabled=True,
                label_visibility="collapsed",
            )


sidebar_branding()
