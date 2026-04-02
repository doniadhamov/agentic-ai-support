"""Shared CSS styles for the admin dashboard."""

SHARED_CSS = """
<style>
/* Global sidebar */
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

/* Pill badges */
.pill-open { background: #dbeafe; color: #1e40af; }
.pill-pending { background: #fce7f3; color: #9d174d; }
.pill-solved { background: #d1fae5; color: #065f46; }
.pill-closed { background: #f3f4f6; color: #4b5563; }

/* Better buttons */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 8px 24px !important;
    font-weight: 600 !important;
    box-shadow: 0 2px 8px rgba(102,126,234,0.3) !important;
}

/* Dataframe styling */
.stDataFrame {
    border-radius: 8px !important;
    overflow: hidden;
}

/* Alert boxes */
.stAlert {
    border-radius: 8px !important;
}

/* Chat message */
.chat-msg {
    padding: 8px 14px;
    margin: 4px 0;
    border-radius: 10px;
    font-size: 0.9rem;
    line-height: 1.5;
}
.chat-user {
    background: #f0f4ff;
    border-left: 3px solid #667eea;
}
.chat-bot {
    background: #f0fdf4;
    border-left: 3px solid #22c55e;
}
.chat-zendesk {
    background: #fef3c7;
    border-left: 3px solid #f59e0b;
}
.chat-meta {
    font-size: 0.75rem;
    color: #6b7280;
    margin-bottom: 2px;
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

/* Navigation cards */
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
.nav-card .card-icon { font-size: 2.5rem; margin-bottom: 12px; }
.nav-card h3 { margin: 0 0 8px 0; font-size: 1.2rem; font-weight: 600; color: #1a1a2e; }
.nav-card p { margin: 0; color: #6b7280; font-size: 0.9rem; line-height: 1.5; }
.nav-card .card-stat {
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid #f0f0f0;
    font-size: 0.85rem;
    color: #667eea;
    font-weight: 600;
}

/* Review card */
.review-card {
    background: white;
    border: 1px solid #e8ecf1;
    border-radius: 10px;
    padding: 16px 20px;
    margin: 8px 0;
}
</style>
"""


def sidebar_branding() -> None:
    """Render standard sidebar branding."""
    import streamlit as st

    with st.sidebar:
        st.markdown("---")
        st.markdown("**DataTruck Admin** v2.0\n\nAI-powered support bot management console.")
