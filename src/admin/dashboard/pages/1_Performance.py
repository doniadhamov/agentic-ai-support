"""Performance page — analytics, trends, top questions, response time breakdown."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st

from src.admin.dashboard.styles import SHARED_CSS, sidebar_branding
from src.admin.dashboard.utils import run_async
from src.database.repositories import get_decision_stats

st.set_page_config(page_title="Performance — DataTruck Admin", layout="wide")
st.markdown(SHARED_CSS, unsafe_allow_html=True)

st.title("📊 Performance")
st.caption(
    "Is the bot getting smarter over time? Analyze trends, top questions, and response times."
)

# --- Date range picker ---
range_options = {
    "Last 7 days": 7,
    "Last 14 days": 14,
    "Last 30 days": 30,
    "Last 90 days": 90,
    "All time": 0,
}
selected_range = st.selectbox("Date range", list(range_options.keys()), index=2)
days = range_options[selected_range]

date_from = datetime.now(tz=UTC) - timedelta(days=days) if days > 0 else None
date_to = None

stats = run_async(get_decision_stats(date_from=date_from, date_to=date_to))

total = stats["total"]
by_action = stats["by_action"]

# --- Top-level metrics ---
answered = by_action.get("answer", 0)
escalated = by_action.get("escalate", 0)
ignored = by_action.get("ignore", 0)
waited = by_action.get("wait", 0)

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.metric("Total Decisions", f"{total:,}")
with c2:
    rate = f"{answered * 100 // total}%" if total else "—"
    st.metric("Answer Rate", rate)
with c3:
    rate = f"{escalated * 100 // total}%" if total else "—"
    st.metric("Escalation Rate", rate)
with c4:
    st.metric("Ignored", f"{ignored:,}")
with c5:
    st.metric("Wait", f"{waited:,}")

st.divider()

# --- Trend chart ---
st.markdown("#### Action Distribution Over Time")
if stats["by_date"]:
    trend_df = pd.DataFrame(stats["by_date"])
    trend_df["date"] = pd.to_datetime(trend_df["date"])
    pivot = trend_df.pivot_table(index="date", columns="action", values="count", fill_value=0)
    st.line_chart(pivot)
else:
    st.info("No trend data available for the selected period.")

st.divider()

# --- Response time breakdown ---
col_timing, col_action_dist = st.columns(2)

with col_timing:
    st.markdown("#### Average Response Time (ms)")
    avg = stats["avg_timing"]
    if avg["total"] > 0:
        timing_data = {
            "Node": ["perceive", "think", "retrieve", "generate", "total"],
            "Avg ms": [
                avg["perceive"],
                avg["think"],
                avg["retrieve"],
                avg["generate"],
                avg["total"],
            ],
        }
        timing_df = pd.DataFrame(timing_data)
        st.bar_chart(timing_df.set_index("Node"))

        # Also show as metrics
        tc1, tc2, tc3, tc4 = st.columns(4)
        with tc1:
            st.metric("Perceive", f"{avg['perceive']}ms")
        with tc2:
            st.metric("Think", f"{avg['think']}ms")
        with tc3:
            st.metric("Retrieve", f"{avg['retrieve']}ms")
        with tc4:
            st.metric("Generate", f"{avg['generate']}ms")
    else:
        st.info("No timing data available.")

with col_action_dist:
    st.markdown("#### Action Distribution")
    if by_action:
        action_df = pd.DataFrame([{"Action": k, "Count": v} for k, v in sorted(by_action.items())])
        st.bar_chart(action_df.set_index("Action"))
    else:
        st.info("No action data available.")

st.divider()

# --- Top escalated questions ---
col_esc, col_ans = st.columns(2)

with col_esc:
    st.markdown("#### Top Escalated Questions")
    st.caption("Questions the bot couldn't answer — write docs for these!")
    if stats["top_escalated"]:
        esc_df = pd.DataFrame(stats["top_escalated"])
        st.dataframe(
            esc_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "question": st.column_config.TextColumn("Question", width="large"),
                "count": st.column_config.NumberColumn("Count", width="small"),
            },
        )
    else:
        st.success("No escalated questions in this period.")

with col_ans:
    st.markdown("#### Top Answered Questions")
    st.caption("Most frequently answered questions — what's working well.")
    if stats["top_answered"]:
        ans_df = pd.DataFrame(stats["top_answered"])
        st.dataframe(
            ans_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "question": st.column_config.TextColumn("Question", width="large"),
                "count": st.column_config.NumberColumn("Count", width="small"),
                "avg_confidence": st.column_config.NumberColumn(
                    "Avg Confidence", format="%.2f", width="small"
                ),
            },
        )
    else:
        st.info("No answered questions in this period.")

sidebar_branding()
