"""Decision Review page — review and correct bot decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st

from src.admin.dashboard.styles import SHARED_CSS, sidebar_branding
from src.admin.dashboard.utils import run_async
from src.database.repositories import (
    get_all_telegram_groups,
    get_bot_decisions,
    update_decision_correction,
)

st.set_page_config(page_title="Decision Review — DataTruck Admin", layout="wide")
st.markdown(SHARED_CSS, unsafe_allow_html=True)

st.title("🔍 Decision Review")
st.caption(
    "Review and correct bot decisions. Corrections feed into procedural memory to improve future accuracy."
)

# --- Filters ---
filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2, 2, 2, 3])

with filter_col1:
    groups = run_async(get_all_telegram_groups())
    group_options = {"All groups": None}
    for g in groups:
        label = g.title or str(g.telegram_chat_id)
        group_options[label] = g.telegram_chat_id
    selected_group_label = st.selectbox("Group", list(group_options.keys()))
    selected_group_id = group_options[selected_group_label]

with filter_col2:
    action_options = ["All", "answer", "ignore", "wait", "escalate"]
    selected_action = st.selectbox("Action", action_options)
    action_filter = selected_action if selected_action != "All" else None

with filter_col3:
    range_options = {
        "Last 24 hours": 1,
        "Last 7 days": 7,
        "Last 30 days": 30,
        "All time": 0,
    }
    selected_range = st.selectbox("Period", list(range_options.keys()), index=1)
    days = range_options[selected_range]
    date_from = datetime.now(tz=UTC) - timedelta(days=days) if days > 0 else None

with filter_col4:
    search_text = st.text_input(
        "Search message text", placeholder="Search...", label_visibility="collapsed"
    )

# --- Load decisions ---
decisions = run_async(
    get_bot_decisions(
        group_id=selected_group_id,
        action_filter=action_filter,
        date_from=date_from,
        search_text=search_text or None,
        limit=100,
    )
)

if not decisions:
    st.info("No decisions match the current filters.")
    sidebar_branding()
    st.stop()

# --- Summary metrics ---
total = len(decisions)
reviewed = sum(1 for d in decisions if d.is_correct is not None)
correct = sum(1 for d in decisions if d.is_correct is True)
incorrect = sum(1 for d in decisions if d.is_correct is False)

mc1, mc2, mc3, mc4 = st.columns(4)
with mc1:
    st.metric("Decisions", total)
with mc2:
    st.metric("Reviewed", reviewed)
with mc3:
    st.metric("Correct", correct)
with mc4:
    st.metric("Incorrect", incorrect)

st.divider()

# --- Decision table ---
rows = []
for d in decisions:
    review_icon = ""
    if d.is_correct is True:
        review_icon = " ✅"
    elif d.is_correct is False:
        review_icon = f" ❌→{d.correct_action}"

    rows.append(
        {
            "ID": d.id,
            "Time": str(d.created_at)[:19] if d.created_at else "",
            "Group": d.group_id,
            "User": d.user_id,
            "Message": (d.message_text or "")[:50],
            "Action": d.action + review_icon,
            "Ticket Action": d.ticket_action,
            "Ticket": d.target_ticket_id or "",
            "Language": d.language,
            "Total ms": d.total_ms or "",
        }
    )

st.dataframe(
    pd.DataFrame(rows),
    use_container_width=True,
    hide_index=True,
    column_config={
        "ID": st.column_config.NumberColumn("ID", width="small"),
        "Time": st.column_config.TextColumn("Time", width="medium"),
        "Group": st.column_config.NumberColumn("Group", width="small"),
        "User": st.column_config.NumberColumn("User", width="small"),
        "Message": st.column_config.TextColumn("Message", width="large"),
        "Action": st.column_config.TextColumn("Action", width="small"),
        "Ticket Action": st.column_config.TextColumn("T.Action", width="small"),
        "Ticket": st.column_config.TextColumn("Ticket", width="small"),
        "Language": st.column_config.TextColumn("Lang", width="small"),
        "Total ms": st.column_config.TextColumn("ms", width="small"),
    },
)

st.caption(f"Showing {len(rows)} decision(s)")

st.divider()

# --- Detail view ---
st.markdown("#### Decision Detail")

decision_ids = [d.id for d in decisions]
selected_id = st.selectbox(
    "Select a decision to review",
    decision_ids,
    format_func=lambda x: (
        f"#{x} — {next((d.message_text or '')[:40] for d in decisions if d.id == x), ''}"
    ),
)

if selected_id:
    dec = next((d for d in decisions if d.id == selected_id), None)
    if dec:
        # Header
        action_color = {
            "answer": "🟢",
            "ignore": "⚪",
            "wait": "🟡",
            "escalate": "🔴",
        }
        icon = action_color.get(dec.action, "⚪")
        st.markdown(
            f"**Decision #{dec.id}** &nbsp; {icon} **{dec.action}** &nbsp; | &nbsp; "
            f"Ticket Action: **{dec.ticket_action}** &nbsp; | &nbsp; "
            f"Language: **{dec.language}**"
        )

        # Message and reasoning
        detail_col1, detail_col2 = st.columns(2)

        with detail_col1:
            st.markdown("**Full Message**")
            st.text_area(
                "msg",
                value=dec.message_text or "",
                height=120,
                disabled=True,
                label_visibility="collapsed",
            )

            if dec.file_description:
                st.markdown(f"**File Description:** {dec.file_description}")

            if dec.extracted_question:
                st.markdown("**Extracted Question**")
                st.text_area(
                    "eq",
                    value=dec.extracted_question,
                    height=80,
                    disabled=True,
                    label_visibility="collapsed",
                )

        with detail_col2:
            st.markdown("**Think Reasoning**")
            st.text_area(
                "reasoning",
                value=dec.reasoning or "",
                height=120,
                disabled=True,
                label_visibility="collapsed",
            )

            if dec.answer_text:
                st.markdown("**Bot Answer**")
                st.text_area(
                    "answer",
                    value=dec.answer_text,
                    height=120,
                    disabled=True,
                    label_visibility="collapsed",
                )

        # Metadata row
        meta_col1, meta_col2, meta_col3, meta_col4 = st.columns(4)
        with meta_col1:
            st.markdown(f"**Group:** `{dec.group_id}`")
        with meta_col2:
            st.markdown(f"**User:** `{dec.user_id}`")
        with meta_col3:
            st.markdown(f"**Urgency:** {dec.urgency}")
        with meta_col4:
            conf = f"{dec.retrieval_confidence:.2f}" if dec.retrieval_confidence else "—"
            st.markdown(f"**Retrieval Confidence:** {conf}")

        # Timing
        if dec.total_ms:
            st.markdown(
                f"**Timing:** perceive={dec.perceive_ms or 0}ms, "
                f"think={dec.think_ms or 0}ms, "
                f"retrieve={dec.retrieve_ms or 0}ms, "
                f"generate={dec.generate_ms or 0}ms, "
                f"**total={dec.total_ms}ms**"
            )

        # Current review status
        if dec.is_correct is not None:
            if dec.is_correct:
                st.success("This decision was marked as **correct**.")
            else:
                st.error(
                    f"This decision was marked as **incorrect**. "
                    f"Correct action: **{dec.correct_action}**"
                )

        st.divider()

        # Correction buttons
        st.markdown("**Review This Decision**")
        btn_col1, btn_col2, btn_col3, btn_col4, btn_col5 = st.columns(5)

        with btn_col1:
            if st.button("✅ Correct", key=f"correct_{dec.id}", type="primary"):
                run_async(update_decision_correction(dec.id, is_correct=True))
                st.success("Marked as correct.")
                st.rerun()

        with btn_col2:
            if st.button("❌ → answer", key=f"wrong_answer_{dec.id}"):
                run_async(
                    update_decision_correction(dec.id, is_correct=False, correct_action="answer")
                )
                st.rerun()

        with btn_col3:
            if st.button("❌ → ignore", key=f"wrong_ignore_{dec.id}"):
                run_async(
                    update_decision_correction(dec.id, is_correct=False, correct_action="ignore")
                )
                st.rerun()

        with btn_col4:
            if st.button("❌ → escalate", key=f"wrong_escalate_{dec.id}"):
                run_async(
                    update_decision_correction(dec.id, is_correct=False, correct_action="escalate")
                )
                st.rerun()

        with btn_col5:
            if st.button("❌ → wait", key=f"wrong_wait_{dec.id}"):
                run_async(
                    update_decision_correction(dec.id, is_correct=False, correct_action="wait")
                )
                st.rerun()


sidebar_branding()
