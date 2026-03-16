"""Main Streamlit app — admin dashboard for the DataTruck support bot."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from src.admin.dashboard.utils import run_async
from src.admin.group_store import GroupStore
from src.config.settings import get_settings

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
/* Global font & background */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown li,
section[data-testid="stSidebar"] .stMarkdown a,
section[data-testid="stSidebar"] span {
    color: #e0e0e0 !important;
}
section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.15) !important;
}

/* Metric cards */
div[data-testid="stMetric"] {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 12px;
    padding: 20px 24px;
    color: white !important;
    box-shadow: 0 4px 15px rgba(102,126,234,0.3);
}
div[data-testid="stMetric"] label {
    color: rgba(255,255,255,0.85) !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: white !important;
    font-size: 2rem !important;
    font-weight: 700 !important;
}

/* Navigation cards on home */
.nav-card {
    background: white;
    border-radius: 12px;
    padding: 28px 24px;
    border: 1px solid #e8ecf1;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    transition: all 0.2s ease;
    min-height: 180px;
}
.nav-card:hover {
    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
    transform: translateY(-2px);
    border-color: #667eea;
}
.nav-card .card-icon {
    font-size: 2.5rem;
    margin-bottom: 12px;
}
.nav-card h3 {
    margin: 0 0 8px 0;
    font-size: 1.2rem;
    font-weight: 600;
    color: #1a1a2e;
}
.nav-card p {
    margin: 0;
    color: #6b7280;
    font-size: 0.9rem;
    line-height: 1.5;
}
.nav-card .card-stat {
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid #f0f0f0;
    font-size: 0.85rem;
    color: #667eea;
    font-weight: 600;
}

/* Status badges */
.status-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.3px;
}
.status-active { background: #d1fae5; color: #065f46; }
.status-inactive { background: #fef3c7; color: #92400e; }
.status-open { background: #dbeafe; color: #1e40af; }
.status-answered { background: #d1fae5; color: #065f46; }
.status-closed { background: #f3f4f6; color: #4b5563; }

/* Better buttons */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 8px 24px !important;
    font-weight: 600 !important;
    box-shadow: 0 2px 8px rgba(102,126,234,0.3) !important;
}

/* Section headers */
.section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 24px 0 16px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid #667eea;
}
.section-header h3 {
    margin: 0;
    color: #1a1a2e;
    font-weight: 600;
}

/* Dataframe styling */
.stDataFrame {
    border-radius: 8px !important;
    overflow: hidden;
}

/* Delete button red */
button[kind="secondary"] {
    border-radius: 8px !important;
}

/* Alert boxes */
.stAlert {
    border-radius: 8px !important;
}

/* Page header with subtitle */
.page-header {
    margin-bottom: 24px;
}
.page-header h1 {
    margin-bottom: 4px;
}
.page-header p {
    color: #6b7280;
    font-size: 1rem;
    margin-top: 0;
}

/* Welcome banner */
.welcome-banner {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 16px;
    padding: 40px 48px;
    color: white;
    margin-bottom: 32px;
}
.welcome-banner h1 {
    color: white !important;
    font-size: 2rem;
    margin-bottom: 8px;
}
.welcome-banner p {
    color: rgba(255,255,255,0.85);
    font-size: 1.1rem;
    margin: 0;
}
</style>
"""


def _check_auth() -> bool:
    """Simple password gate. Returns True if authenticated or no password set."""
    settings = get_settings()
    if not settings.admin_password:
        return True

    if st.session_state.get("authenticated"):
        return True

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
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


def _load_ticket_counts() -> dict[str, int]:
    """Load ticket status counts from tickets.json."""
    tickets_path = Path("data/tickets.json")
    counts: dict[str, int] = {"total": 0, "open": 0, "answered": 0, "closed": 0}
    if tickets_path.exists():
        try:
            raw = json.loads(tickets_path.read_text())
            counts["total"] = len(raw)
            for record in raw.values():
                status = record.get("status", "").lower()
                if status in counts:
                    counts[status] += 1
        except Exception:
            pass
    return counts


def main() -> None:
    st.set_page_config(
        page_title="DataTruck Admin",
        page_icon=":material/admin_panel_settings:",
        layout="wide",
    )

    if not _check_auth():
        st.stop()

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # --- Welcome banner ---
    st.markdown(
        '<div class="welcome-banner">'
        "<h1>DataTruck Admin Dashboard</h1>"
        "<p>Monitor and manage your AI support bot — groups, knowledge base, documents, and tickets</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # --- Quick stats row ---
    group_store = GroupStore()
    groups = group_store.list_groups()
    ticket_counts = _load_ticket_counts()

    # Try to get Qdrant point counts
    docs_count = 0
    memory_count = 0
    try:
        from src.vector_db.collections import DOCS_COLLECTION, MEMORY_COLLECTION
        from src.vector_db.qdrant_client import get_qdrant_client

        qdrant = get_qdrant_client()
        docs_count = run_async(qdrant.count_points(DOCS_COLLECTION))
        memory_count = run_async(qdrant.count_points(MEMORY_COLLECTION))
    except Exception:
        pass

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Active Groups", len(groups))
    with c2:
        st.metric("Knowledge Chunks", f"{docs_count:,}")
    with c3:
        st.metric("Memory Entries", f"{memory_count:,}")
    with c4:
        st.metric("Open Tickets", ticket_counts["open"])

    st.markdown("")

    # --- Navigation cards ---
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        status_class = "status-active" if groups else "status-inactive"
        status_text = "Active" if groups else "Inactive"
        st.markdown(
            f"""<div class="nav-card">
                <div class="card-icon">👥</div>
                <h3>Groups</h3>
                <p>Manage Telegram group allowlist. Add or remove groups that the bot monitors.</p>
                <div class="card-stat">
                    <span class="status-badge {status_class}">{status_text}</span>
                    &nbsp; {len(groups)} group(s)
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""<div class="nav-card">
                <div class="card-icon">📚</div>
                <h3>Knowledge Base</h3>
                <p>Browse Qdrant collections, view vectors, and sync with Zendesk.</p>
                <div class="card-stat">{docs_count:,} docs &bull; {memory_count:,} memories</div>
            </div>""",
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            """<div class="nav-card">
                <div class="card-icon">📄</div>
                <h3>Upload</h3>
                <p>Ingest PDF, DOCX, TXT, and Markdown files into the knowledge base.</p>
                <div class="card-stat">Drag & drop supported</div>
            </div>""",
            unsafe_allow_html=True,
        )

    with col4:
        open_count = ticket_counts["open"]
        badge = (
            f'<span class="status-badge status-open">{open_count} open</span>'
            if open_count > 0
            else '<span class="status-badge status-closed">No open tickets</span>'
        )
        st.markdown(
            f"""<div class="nav-card">
                <div class="card-icon">🎫</div>
                <h3>Tickets</h3>
                <p>View escalated support questions and their resolution status.</p>
                <div class="card-stat">
                    {badge}
                    &nbsp; {ticket_counts['total']} total
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

    # --- Sidebar branding ---
    with st.sidebar:
        st.markdown("---")
        st.markdown(
            "**DataTruck Admin** v1.0\n\n"
            "AI-powered support bot management console."
        )


if __name__ == "__main__":
    main()
