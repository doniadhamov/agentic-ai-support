"""Tickets page — view conversation threads and Zendesk tickets."""

from __future__ import annotations

import asyncio

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Tickets — DataTruck Admin", layout="wide")

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

.status-pill {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.3px;
}
.pill-active { background: #dbeafe; color: #1e40af; }
.pill-closed { background: #f3f4f6; color: #4b5563; }
.pill-new { background: #fef3c7; color: #92400e; }
.pill-open { background: #dbeafe; color: #1e40af; }
.pill-pending { background: #fce7f3; color: #9d174d; }
.pill-solved { background: #d1fae5; color: #065f46; }
</style>
""",
    unsafe_allow_html=True,
)

# --- Page header ---
st.title("🎫 Conversation Threads")
st.caption("View Telegram ↔ Zendesk conversation threads.")


def _load_threads() -> list[dict]:
    """Load conversation threads from the database."""
    try:
        from src.config.settings import get_settings

        settings = get_settings()
        if not settings.database_url:
            return []

        from sqlalchemy import select

        from src.database.engine import get_engine, get_session_factory
        from src.database.models import ConversationThread

        # Ensure engine is initialized
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
                        "created_at": str(t.created_at)[:19] if t.created_at else "—",
                        "closed_at": str(t.closed_at)[:19] if t.closed_at else "—",
                        "last_message_at": str(t.last_message_at)[:19] if t.last_message_at else "—",
                    }
                    for t in threads
                ]

        return asyncio.run(_fetch())
    except Exception as exc:
        st.error(f"Failed to load threads from database: {exc}")
        return []


threads = _load_threads()

if not threads:
    st.info("No conversation threads yet. Threads will appear here as messages are synced to Zendesk.")
    st.stop()

# --- Status counts ---
status_counts: dict[str, int] = {}
for t in threads:
    s = t.get("status", "unknown")
    status_counts[s] = status_counts.get(s, 0) + 1

c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Total Threads", len(threads))
with c2:
    st.metric("Active", status_counts.get("active", 0))
with c3:
    st.metric("Closed", status_counts.get("closed", 0))

st.markdown("")

# --- Filter controls ---
filter_col1, filter_col2 = st.columns([1, 4])
with filter_col1:
    all_statuses = sorted({t.get("status", "unknown") for t in threads})
    selected_status = st.selectbox("Status", ["All"] + all_statuses, label_visibility="collapsed")
with filter_col2:
    search_query = st.text_input(
        "Search",
        placeholder="🔍 Search by subject...",
        label_visibility="collapsed",
    )

# --- Build filtered rows ---
rows = []
zendesk_subdomain = "support.datatruck.io"
try:
    from src.config.settings import get_settings

    zendesk_subdomain = get_settings().zendesk_subdomain
except Exception:
    pass

for t in threads:
    if selected_status != "All" and t.get("status") != selected_status:
        continue
    if search_query and search_query.lower() not in (t.get("subject", "") or "").lower():
        continue

    ticket_id = t.get("zendesk_ticket_id", 0)
    rows.append(
        {
            "Thread ID": t.get("id", "—"),
            "Zendesk Ticket": ticket_id,
            "Subject": (t.get("subject", "") or "")[:100],
            "Status": t.get("status", "unknown"),
            "Group": t.get("group_id", "—"),
            "User": t.get("user_id", "—"),
            "Last Message": t.get("last_message_at", "—"),
            "Created": t.get("created_at", "—"),
        }
    )

if not rows:
    st.warning("No threads match the current filters.")
else:
    # Add status indicator
    def _status_icon(status: str) -> str:
        s = status.lower()
        if s == "active":
            return "🔵"
        if s == "closed":
            return "⚪"
        return "🟡"

    for row in rows:
        row["Status"] = f"{_status_icon(row['Status'])} {row['Status']}"

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Thread ID": st.column_config.NumberColumn("Thread", width="small"),
            "Zendesk Ticket": st.column_config.NumberColumn("Zendesk #", width="small"),
            "Subject": st.column_config.TextColumn("Subject", width="large"),
            "Status": st.column_config.TextColumn("Status", width="small"),
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
        "Select a thread to view details",
        thread_ids,
        label_visibility="collapsed",
    )

    if selected_thread_id:
        thread_data = next((t for t in threads if t.get("id") == selected_thread_id), None)
        if thread_data:
            status = thread_data.get("status", "unknown").lower()
            pill_class = f"pill-{status}" if status in ("active", "closed") else "pill-active"
            ticket_id = thread_data.get("zendesk_ticket_id", 0)

            # Header row
            zendesk_link = f"https://{zendesk_subdomain}/agent/tickets/{ticket_id}"
            st.markdown(
                f'**Thread #{selected_thread_id}** &nbsp; '
                f'<span class="status-pill {pill_class}">{thread_data.get("status", "unknown")}</span>'
                f' &nbsp; | &nbsp; '
                f'<a href="{zendesk_link}" target="_blank">View in Zendesk →</a>',
                unsafe_allow_html=True,
            )

            # Info columns
            meta_col1, meta_col2, meta_col3 = st.columns(3)
            with meta_col1:
                st.markdown(f"**Group ID:** `{thread_data.get('group_id', '—')}`")
                st.markdown(f"**User ID:** `{thread_data.get('user_id', '—')}`")
            with meta_col2:
                st.markdown(f"**Zendesk Ticket:** `{ticket_id}`")
                st.markdown(f"**Status:** {thread_data.get('status', '—')}")
            with meta_col3:
                st.markdown(f"**Created:** {thread_data.get('created_at', '—')}")
                st.markdown(f"**Closed:** {thread_data.get('closed_at', '—')}")

            st.markdown("")

            # Subject
            st.markdown("**Subject**")
            st.text_area(
                "subject_detail",
                value=thread_data.get("subject", ""),
                height=80,
                disabled=True,
                label_visibility="collapsed",
            )

# --- Sidebar ---
with st.sidebar:
    st.markdown("---")
    st.markdown(
        "**DataTruck Admin** v1.0\n\n"
        "AI-powered support bot management console."
    )
