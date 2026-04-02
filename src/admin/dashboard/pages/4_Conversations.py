"""Conversations page — monitor live conversations across all groups."""

from __future__ import annotations

import streamlit as st

from src.admin.dashboard.styles import SHARED_CSS, sidebar_branding
from src.admin.dashboard.utils import run_async
from src.database.repositories import (
    get_active_threads_in_group,
    get_all_telegram_groups,
    get_messages_for_group,
)

st.set_page_config(page_title="Conversations — DataTruck Admin", layout="wide")
st.markdown(SHARED_CSS, unsafe_allow_html=True)

st.title("💬 Conversations")
st.caption("Monitor live conversations across all groups.")

# --- Group selector ---
groups = run_async(get_all_telegram_groups())
active_groups = [g for g in groups if g.active]

if not groups:
    st.info("No groups registered. Add groups in the Groups page first.")
    sidebar_branding()
    st.stop()

group_options = {(g.title or str(g.telegram_chat_id)): g.telegram_chat_id for g in groups}
selected_label = st.selectbox("Select Group", list(group_options.keys()))
selected_chat_id = group_options[selected_label]

# --- Layout: messages + sidebar ---
msg_col, sidebar_col = st.columns([3, 1])

with sidebar_col:
    st.markdown("#### Active Tickets")
    threads = run_async(get_active_threads_in_group(selected_chat_id))
    if threads:
        for t in threads:
            status_icon = "🔵" if t.status == "open" else "🟡"
            st.markdown(
                f"{status_icon} **#{t.zendesk_ticket_id}**: {(t.subject or '')[:40]}\n\n"
                f"<span style='font-size:0.8rem;color:#6b7280;'>"
                f"User: {t.user_id} | {t.status}</span>",
                unsafe_allow_html=True,
            )
            st.markdown("---")
    else:
        st.info("No active tickets in this group.")

    st.markdown("#### Group Info")
    st.markdown(f"**Chat ID:** `{selected_chat_id}`")
    st.markdown(f"**Title:** {selected_label}")

with msg_col:
    st.markdown("#### Recent Messages")

    # Load messages
    messages = run_async(get_messages_for_group(selected_chat_id, limit=100))

    if not messages:
        st.info("No messages in this group yet.")
    else:
        # Render as chat-like view
        for msg in messages:
            source = msg.get("source", "telegram")
            username = msg.get("username", "Unknown")
            text = msg.get("text", "")
            file_type = msg.get("file_type")
            file_desc = msg.get("file_description")
            created_at = msg.get("created_at")
            ticket_id = msg.get("zendesk_ticket_id")

            # Build display text
            display_text = text
            if file_type == "photo" and file_desc:
                display_text = f"[Photo: {file_desc}]"
                if text:
                    display_text += f" {text}"
            elif file_type == "voice":
                display_text = f"[Voice] {text}"
            elif file_type == "document" and file_desc:
                display_text = f"[File: {file_desc}]"
                if text:
                    display_text += f" {text}"

            if not display_text.strip():
                display_text = "[empty message]"

            # Source styling
            if source == "bot":
                css_class = "chat-bot"
                sender_label = "🤖 Bot"
            elif source == "zendesk":
                css_class = "chat-zendesk"
                sender_label = f"👤 Agent ({username})"
            else:
                css_class = "chat-user"
                sender_label = f"💬 {username}"

            time_str = str(created_at)[:19] if created_at else ""
            ticket_badge = f" | Ticket #{ticket_id}" if ticket_id else ""

            # Escape HTML in display_text
            safe_text = (
                display_text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )

            st.markdown(
                f'<div class="chat-msg {css_class}">'
                f'<div class="chat-meta">{sender_label} &nbsp; {time_str}{ticket_badge}</div>'
                f"{safe_text}"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.caption(f"Showing {len(messages)} message(s)")


sidebar_branding()
