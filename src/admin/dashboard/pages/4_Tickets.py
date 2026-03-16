"""Tickets page — read-only view of escalated support tickets."""

from __future__ import annotations

import json
from pathlib import Path

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

.ticket-detail-card {
    background: white;
    border: 1px solid #e8ecf1;
    border-radius: 12px;
    padding: 24px;
    margin: 8px 0;
}
.status-pill {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.3px;
}
.pill-open { background: #dbeafe; color: #1e40af; }
.pill-answered { background: #d1fae5; color: #065f46; }
.pill-closed { background: #f3f4f6; color: #4b5563; }
</style>
""",
    unsafe_allow_html=True,
)

# --- Page header ---
st.title("🎫 Escalated Tickets")
st.caption("View support questions that were escalated to human agents.")

# --- Load tickets ---
tickets_path = Path("data/tickets.json")
if not tickets_path.exists():
    st.info("No tickets file found. Tickets will appear here after the bot escalates questions.")
    st.stop()

try:
    raw: dict = json.loads(tickets_path.read_text())
except Exception as exc:
    st.error(f"Failed to read tickets file: {exc}")
    st.stop()

if not raw:
    st.info("No tickets yet. Escalated questions will appear here.")
    st.stop()

# --- Status counts ---
status_counts = {"open": 0, "answered": 0, "closed": 0}
for record in raw.values():
    s = record.get("status", "").lower()
    if s in status_counts:
        status_counts[s] += 1

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Total Tickets", len(raw))
with c2:
    st.metric("Open", status_counts["open"])
with c3:
    st.metric("Answered", status_counts["answered"])
with c4:
    st.metric("Closed", status_counts["closed"])

st.markdown("")

# --- Filter controls ---
filter_col1, filter_col2 = st.columns([1, 4])
with filter_col1:
    all_statuses = sorted({r.get("status", "unknown") for r in raw.values()})
    selected_status = st.selectbox("Status", ["All"] + all_statuses, label_visibility="collapsed")
with filter_col2:
    search_query = st.text_input(
        "Search",
        placeholder="🔍 Search tickets by question text...",
        label_visibility="collapsed",
    )

# --- Build filtered rows ---
rows = []
for ticket_id, record in raw.items():
    if selected_status != "All" and record.get("status") != selected_status:
        continue
    if search_query:
        question = (record.get("question", "") or "").lower()
        if search_query.lower() not in question:
            continue

    status = record.get("status", "unknown")
    rows.append(
        {
            "Ticket ID": ticket_id,
            "Question": (record.get("question", "") or "")[:120],
            "Status": status,
            "Group": record.get("group_id", "—"),
            "User": record.get("user_id", "—"),
            "Created": record.get("created_at", "—"),
        }
    )

if not rows:
    st.warning("No tickets match the current filters.")
else:
    # --- Status pill helper ---
    def _status_color(status: str) -> str:
        s = status.lower()
        if s == "open":
            return "🔵"
        if s == "answered":
            return "🟢"
        return "⚪"

    # Add status indicator to rows
    for row in rows:
        row["Status"] = f"{_status_color(row['Status'])} {row['Status']}"

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ticket ID": st.column_config.TextColumn("Ticket ID", width="medium"),
            "Question": st.column_config.TextColumn("Question", width="large"),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Group": st.column_config.NumberColumn("Group", width="small"),
            "User": st.column_config.NumberColumn("User", width="small"),
            "Created": st.column_config.TextColumn("Created", width="medium"),
        },
    )

    st.caption(f"Showing {len(rows)} of {len(raw)} ticket(s)")

    st.divider()

    # --- Detail view ---
    st.markdown("#### Ticket Details")

    ticket_ids = [r["Ticket ID"] for r in rows]
    selected_ticket = st.selectbox(
        "Select a ticket to view details",
        ticket_ids,
        label_visibility="collapsed",
    )

    if selected_ticket and selected_ticket in raw:
        record = raw[selected_ticket]
        status = record.get("status", "unknown").lower()
        pill_class = f"pill-{status}" if status in ("open", "answered", "closed") else "pill-closed"

        # Header row
        st.markdown(
            f'**{selected_ticket}** &nbsp; '
            f'<span class="status-pill {pill_class}">{record.get("status", "unknown")}</span>',
            unsafe_allow_html=True,
        )

        # Info columns
        meta_col1, meta_col2, meta_col3 = st.columns(3)
        with meta_col1:
            st.markdown(f"**Group ID:** `{record.get('group_id', '—')}`")
        with meta_col2:
            st.markdown(f"**User ID:** `{record.get('user_id', '—')}`")
        with meta_col3:
            st.markdown(f"**Created:** {record.get('created_at', '—')}")

        st.markdown("")

        # Question
        st.markdown("**Question**")
        st.text_area(
            "question_detail",
            value=record.get("question", ""),
            height=150,
            disabled=True,
            label_visibility="collapsed",
        )

        # Answer
        answer = record.get("answer")
        if answer:
            st.markdown("**Answer**")
            st.text_area(
                "answer_detail",
                value=answer,
                height=150,
                disabled=True,
                label_visibility="collapsed",
            )
        else:
            st.info("No answer yet — waiting for human support agent response.")

# --- Sidebar ---
with st.sidebar:
    st.markdown("---")
    st.markdown(
        "**DataTruck Admin** v1.0\n\n"
        "AI-powered support bot management console."
    )
