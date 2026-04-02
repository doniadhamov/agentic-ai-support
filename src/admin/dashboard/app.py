"""Main Streamlit app — admin dashboard for the DataTruck support bot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st

from src.admin.dashboard.styles import SHARED_CSS, sidebar_branding
from src.admin.dashboard.utils import run_async
from src.config.settings import get_settings


def _check_auth() -> bool:
    """Simple password gate. Returns True if authenticated or no password set."""
    settings = get_settings()
    if not settings.admin_password:
        return True

    if st.session_state.get("authenticated"):
        return True

    st.markdown(SHARED_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="welcome-banner">'
        "<h1>DataTruck Admin</h1>"
        "<p>Enter your password to continue</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", type="primary", use_container_width=True):
            if password == settings.admin_password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Invalid password")
    return False


def main() -> None:
    st.set_page_config(
        page_title="DataTruck Admin",
        page_icon=":material/admin_panel_settings:",
        layout="wide",
    )

    if not _check_auth():
        st.stop()

    st.markdown(SHARED_CSS, unsafe_allow_html=True)

    # --- Welcome banner ---
    st.markdown(
        '<div class="welcome-banner">'
        "<h1>DataTruck Admin Dashboard</h1>"
        "<p>Monitor and manage your AI support bot — performance, knowledge, decisions, and conversations</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # --- Load data ---
    from src.database.repositories import (
        get_all_telegram_groups,
        get_decision_stats,
    )

    today_start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    all_groups = run_async(get_all_telegram_groups())
    active_groups = [g for g in all_groups if g.active]

    # Today's decision stats
    today_stats = run_async(get_decision_stats(date_from=today_start))

    # Qdrant counts
    memory_count = 0
    docs_articles = 0
    try:
        from src.vector_db.collections import DOCS_COLLECTION, MEMORY_COLLECTION
        from src.vector_db.qdrant_client import get_qdrant_client

        qdrant = get_qdrant_client()
        memory_count = run_async(qdrant.count_points(MEMORY_COLLECTION))

        async def _count_articles() -> int:
            article_ids: set = set()
            offset = None
            while True:
                points, offset = await qdrant.scroll_points(
                    DOCS_COLLECTION, limit=100, offset=offset
                )
                for pt in points:
                    aid = (pt.payload or {}).get("article_id")
                    if aid is not None:
                        article_ids.add(aid)
                if offset is None:
                    break
            return len(article_ids)

        docs_articles = run_async(_count_articles())
    except Exception:
        pass

    # Open tickets count
    open_tickets = 0
    try:
        from src.database.repositories import get_open_tickets_by_group

        tickets_by_group = run_async(get_open_tickets_by_group())
        open_tickets = sum(tickets_by_group.values())
    except Exception:
        pass

    # --- Quick stats row ---
    total_today = today_stats["total"]
    by_action = today_stats["by_action"]
    answered_today = by_action.get("answer", 0)
    escalated_today = by_action.get("escalate", 0)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Messages Today", total_today)
    with c2:
        pct = f"({answered_today * 100 // total_today}%)" if total_today else ""
        st.metric("Answered Today", f"{answered_today} {pct}")
    with c3:
        pct = f"({escalated_today * 100 // total_today}%)" if total_today else ""
        st.metric("Escalated Today", f"{escalated_today} {pct}")
    with c4:
        st.metric("Learned Q&A", f"{memory_count:,}")
    with c5:
        st.metric("Active Groups", len(active_groups))

    st.markdown("")

    # --- Action distribution & Recent activity ---
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.markdown("#### Action Distribution (Today)")
        if total_today > 0:
            action_df = pd.DataFrame(
                [{"Action": action, "Count": count} for action, count in sorted(by_action.items())]
            )
            st.bar_chart(action_df.set_index("Action"), horizontal=True)
        else:
            st.info("No decisions recorded today yet.")

    with col_right:
        st.markdown("#### Trend (Last 30 Days)")
        stats_30d = run_async(
            get_decision_stats(date_from=datetime.now(tz=UTC) - timedelta(days=30))
        )
        if stats_30d["by_date"]:
            trend_df = pd.DataFrame(stats_30d["by_date"])
            trend_df["date"] = pd.to_datetime(trend_df["date"])
            pivot = trend_df.pivot_table(
                index="date", columns="action", values="count", fill_value=0
            )
            st.line_chart(pivot)
        else:
            st.info("No data for trend chart yet.")

    st.divider()

    # --- Recent bot decisions ---
    st.markdown("#### Recent Bot Decisions")
    from src.database.repositories import get_bot_decisions

    recent = run_async(get_bot_decisions(limit=10))
    if recent:
        rows = []
        for d in recent:
            rows.append(
                {
                    "Time": str(d.created_at)[:19] if d.created_at else "",
                    "Group": d.group_id,
                    "User": d.user_id,
                    "Message": (d.message_text or "")[:60],
                    "Action": d.action,
                    "Ticket Action": d.ticket_action,
                    "Ticket": d.target_ticket_id or "",
                    "Total ms": d.total_ms or "",
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info(
            "No bot decisions recorded yet. Decisions will appear here as messages are processed."
        )

    st.markdown("")

    # --- Navigation cards ---
    st.markdown("#### Quick Navigation")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            f"""<div class="nav-card">
                <div class="card-icon">📊</div>
                <h3>Performance</h3>
                <p>Analytics, trends, top questions, and response time breakdown.</p>
                <div class="card-stat">{total_today} decisions today</div>
            </div>""",
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""<div class="nav-card">
                <div class="card-icon">📚</div>
                <h3>Knowledge Base</h3>
                <p>Documentation, learned Q&A, quick add, Zendesk import, and uploads.</p>
                <div class="card-stat">{docs_articles} articles &bull; {memory_count} memories</div>
            </div>""",
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            f"""<div class="nav-card">
                <div class="card-icon">🔍</div>
                <h3>Decision Review</h3>
                <p>Review and correct bot decisions to improve accuracy over time.</p>
                <div class="card-stat">{open_tickets} open tickets</div>
            </div>""",
            unsafe_allow_html=True,
        )

    col4, col5, col6 = st.columns(3)

    with col4:
        st.markdown(
            """<div class="nav-card">
                <div class="card-icon">💬</div>
                <h3>Conversations</h3>
                <p>Monitor live conversations across all groups.</p>
            </div>""",
            unsafe_allow_html=True,
        )

    with col5:
        status_class = "status-active" if active_groups else "status-inactive"
        status_text = "Active" if active_groups else "Inactive"
        st.markdown(
            f"""<div class="nav-card">
                <div class="card-icon">👥</div>
                <h3>Groups</h3>
                <p>Manage Telegram group allowlist.</p>
                <div class="card-stat">
                    <span class="status-badge {status_class}">{status_text}</span>
                    &nbsp; {len(active_groups)} group(s)
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

    with col6:
        st.markdown(
            """<div class="nav-card">
                <div class="card-icon">🎫</div>
                <h3>Tickets</h3>
                <p>View conversation threads and Zendesk tickets.</p>
            </div>""",
            unsafe_allow_html=True,
        )

    sidebar_branding()


if __name__ == "__main__":
    main()
