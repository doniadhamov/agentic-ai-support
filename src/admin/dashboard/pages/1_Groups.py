"""Groups management page — manage the Telegram group allowlist."""

from __future__ import annotations

import streamlit as st

from src.admin.group_store import GroupStore

st.set_page_config(page_title="Groups — DataTruck Admin", layout="wide")

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

.group-row {
    background: white;
    border: 1px solid #e8ecf1;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    transition: all 0.15s ease;
}
.group-row:hover {
    border-color: #667eea;
    box-shadow: 0 2px 8px rgba(102,126,234,0.12);
}
.group-id {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.9rem;
    background: #f0f4ff;
    padding: 4px 10px;
    border-radius: 6px;
    color: #4338ca;
    font-weight: 600;
}
.group-name {
    font-weight: 500;
    color: #1a1a2e;
}
.group-date {
    color: #9ca3af;
    font-size: 0.85rem;
}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def _get_store() -> GroupStore:
    return GroupStore()


store = _get_store()

# --- Page header ---
st.title("👥 Telegram Group Allowlist")
st.caption("Manage which Telegram groups the bot monitors and responds in.")

# --- Status metrics ---
groups = store.list_groups()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Groups", len(groups))
with col2:
    status = "Active" if groups else "Inactive"
    st.metric("Allowlist Status", status)
with col3:
    st.metric("Mode", "Allowlist" if groups else "All Groups")

st.markdown("")

if groups:
    st.success(
        f"Allowlist is **active** — the bot only responds in **{len(groups)}** registered group(s)."
    )
else:
    st.warning(
        "Allowlist is **inactive** — the bot currently accepts messages from **all** groups. "
        "Add a group below to activate the allowlist."
    )

# --- Add group form ---
st.markdown("#### Add New Group")
with st.form("add_group", clear_on_submit=True):
    col1, col2, col3 = st.columns([2, 3, 1])
    with col1:
        group_id = st.number_input(
            "Group ID",
            value=0,
            step=1,
            format="%d",
            help="Telegram group chat ID (negative number for groups/supergroups). "
            "You can get this from the bot logs or using @userinfobot.",
        )
    with col2:
        group_name = st.text_input(
            "Display Name",
            placeholder="e.g. DataTruck Support RU",
        )
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("➕ Add Group", type="primary", use_container_width=True)

    if submitted:
        if group_id == 0:
            st.error("Group ID cannot be zero.")
        else:
            store.add_group(int(group_id), group_name)
            st.success(f"Added group **{group_name or group_id}**")
            st.rerun()

st.divider()

# --- Groups table ---
st.markdown("#### Registered Groups")
if not groups:
    st.info("No groups in the allowlist yet. The bot will respond to messages from all groups.")
else:
    # Search / filter
    search = st.text_input(
        "🔍 Search groups",
        placeholder="Filter by name or ID...",
        label_visibility="collapsed",
    )

    filtered = groups
    if search:
        search_lower = search.lower()
        filtered = [
            g
            for g in groups
            if search_lower in (g.name or "").lower() or search_lower in str(g.group_id)
        ]

    if not filtered:
        st.warning("No groups match your search.")
    else:
        # Table header
        hdr1, hdr2, hdr3, hdr4 = st.columns([2, 3, 3, 1])
        with hdr1:
            st.markdown("**Group ID**")
        with hdr2:
            st.markdown("**Name**")
        with hdr3:
            st.markdown("**Added**")
        with hdr4:
            st.markdown("**Action**")

        for group in filtered:
            c1, c2, c3, c4 = st.columns([2, 3, 3, 1])
            with c1:
                st.code(str(group.group_id), language=None)
            with c2:
                st.markdown(f"**{group.name}**" if group.name else "*Unnamed*")
            with c3:
                st.caption(group.added_at.strftime("%b %d, %Y  %H:%M UTC"))
            with c4:
                if st.button("🗑️", key=f"del_{group.group_id}", help=f"Remove group {group.group_id}"):
                    store.remove_group(group.group_id)
                    st.rerun()

    st.caption(f"Showing {len(filtered)} of {len(groups)} group(s)")

# --- Sidebar ---
with st.sidebar:
    st.markdown("---")
    st.markdown(
        "**DataTruck Admin** v1.0\n\n"
        "AI-powered support bot management console."
    )
