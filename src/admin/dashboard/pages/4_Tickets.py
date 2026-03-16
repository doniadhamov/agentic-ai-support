"""Tickets page — read-only view of escalated support tickets."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Tickets — DataTruck Admin", layout="wide")
st.title("Escalated Tickets")

st.info("This page is read-only. Full ticket management will be implemented in a future update.")

# --- Load tickets from JSON file ---
tickets_path = Path("data/tickets.json")
if not tickets_path.exists():
    st.warning("No tickets file found. Tickets will appear here after the bot escalates questions.")
    st.stop()

try:
    raw = json.loads(tickets_path.read_text())
except Exception as exc:
    st.error(f"Failed to read tickets file: {exc}")
    st.stop()

if not raw:
    st.info("No tickets yet.")
    st.stop()

# --- Filter controls ---
all_statuses = sorted({r.get("status", "unknown") for r in raw.values()})
selected_status = st.selectbox("Filter by status", ["All"] + all_statuses)

# --- Build table ---
rows = []
for ticket_id, record in raw.items():
    if selected_status != "All" and record.get("status") != selected_status:
        continue
    rows.append(
        {
            "Ticket ID": ticket_id,
            "Group ID": record.get("group_id", "—"),
            "User ID": record.get("user_id", "—"),
            "Question": (record.get("question", "") or "")[:100],
            "Status": record.get("status", "unknown"),
            "Answer": (record.get("answer", "") or "")[:100] or "—",
            "Created": record.get("created_at", "—"),
        }
    )

if not rows:
    st.info("No tickets match the selected filter.")
else:
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # --- Detail view ---
    st.subheader("Ticket Detail")
    ticket_ids = [r["Ticket ID"] for r in rows]
    selected_ticket = st.selectbox("Select ticket", ticket_ids)
    if selected_ticket and selected_ticket in raw:
        record = raw[selected_ticket]
        col1, col2 = st.columns(2)
        with col1:
            st.write("**Ticket ID:**", selected_ticket)
            st.write("**Status:**", record.get("status", "—"))
            st.write("**Group ID:**", record.get("group_id", "—"))
            st.write("**User ID:**", record.get("user_id", "—"))
            st.write("**Created:**", record.get("created_at", "—"))
        with col2:
            st.write("**Question:**")
            st.text_area(
                "question_detail",
                value=record.get("question", ""),
                height=150,
                disabled=True,
                label_visibility="collapsed",
            )
            if record.get("answer"):
                st.write("**Answer:**")
                st.text_area(
                    "answer_detail",
                    value=record.get("answer", ""),
                    height=150,
                    disabled=True,
                    label_visibility="collapsed",
                )
