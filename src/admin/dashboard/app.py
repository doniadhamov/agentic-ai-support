"""Main Streamlit app — admin dashboard for the DataTruck support bot."""

from __future__ import annotations

import streamlit as st

from src.config.settings import get_settings


def _check_auth() -> bool:
    """Simple password gate. Returns True if authenticated or no password set."""
    settings = get_settings()
    if not settings.admin_password:
        return True

    if st.session_state.get("authenticated"):
        return True

    st.title("Admin Dashboard")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Login"):
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

    # Main landing page
    st.title("DataTruck Admin Dashboard")
    st.markdown("Use the sidebar to navigate between pages.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("### Groups")
        st.markdown("Manage Telegram group allowlist")
    with col2:
        st.markdown("### Knowledge Base")
        st.markdown("Browse & manage vector store")
    with col3:
        st.markdown("### Upload")
        st.markdown("Ingest PDF, DOCX, TXT files")
    with col4:
        st.markdown("### Tickets")
        st.markdown("View escalated questions")


if __name__ == "__main__":
    main()
