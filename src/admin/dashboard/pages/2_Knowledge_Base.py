"""Knowledge Base page — browse Qdrant collections and trigger sync."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.admin.dashboard.utils import run_async
from src.vector_db.collections import DOCS_COLLECTION, MEMORY_COLLECTION
from src.vector_db.qdrant_client import get_qdrant_client

st.set_page_config(page_title="Knowledge Base — DataTruck Admin", layout="wide")

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

.collection-tab {
    background: white;
    border: 1px solid #e8ecf1;
    border-radius: 10px;
    padding: 16px;
}
</style>
""",
    unsafe_allow_html=True,
)

# --- Page header ---
st.title("📚 Knowledge Base")
st.caption("Browse Qdrant vector collections, manage documents, and synchronize with Zendesk.")

qdrant = get_qdrant_client()

# --- Collection selector as tabs ---
tab_docs, tab_memory = st.tabs([f"📄 {DOCS_COLLECTION}", f"🧠 {MEMORY_COLLECTION}"])


def _render_collection(collection: str) -> None:
    """Render stats, sync controls, and point browser for a collection."""

    # --- Collection stats ---
    try:
        info = run_async(qdrant.get_collection_info(collection))
        point_count = info.points_count or 0

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Total Points", f"{point_count:,}")
        with c2:
            vectors_config = info.config.params.vectors
            size = vectors_config.size if hasattr(vectors_config, "size") else "—"
            st.metric("Vector Dimensions", size)
        with c3:
            st.metric("Distance Metric", "Cosine")
        with c4:
            status_val = info.status.value if info.status else "unknown"
            st.metric("Status", status_val.capitalize())
    except Exception as exc:
        st.error(f"Failed to fetch collection info: {exc}")
        st.stop()

    st.markdown("")

    # --- Sync controls (only for docs collection) ---
    if collection == DOCS_COLLECTION:
        st.markdown("#### 🔄 Zendesk Sync")
        sync_col1, sync_col2, sync_col3 = st.columns([2, 2, 3])

        with sync_col1:
            if st.button("⚡ Delta Sync (24h)", type="primary", use_container_width=True, key=f"delta_{collection}"):
                with st.spinner("Running delta sync..."):
                    try:
                        from src.embeddings.gemini_embedder import GeminiEmbedder
                        from src.ingestion.sync_manager import SyncManager
                        from src.vector_db.indexer import ArticleIndexer

                        async def _delta_sync() -> dict:
                            embedder = GeminiEmbedder()
                            indexer = ArticleIndexer(embedder=embedder, qdrant=qdrant)

                            async def on_chunks(chunks: list) -> None:
                                await indexer.index_chunks(chunks)

                            mgr = SyncManager(on_chunks=on_chunks)
                            return await mgr.delta_sync()

                        stats = run_async(_delta_sync())
                        st.success(
                            f"Synced **{stats['articles']}** article(s), "
                            f"**{stats['chunks']}** chunk(s)"
                        )
                    except Exception as exc:
                        st.error(f"Sync failed: {exc}")

        with sync_col2:
            if st.button("🔃 Full Re-ingest", type="secondary", use_container_width=True, key=f"full_{collection}"):
                st.session_state[f"show_full_confirm_{collection}"] = True

        with sync_col3:
            if st.session_state.get(f"show_full_confirm_{collection}"):
                st.warning("This will re-ingest all Zendesk articles. This may take several minutes.")
                confirm_col1, confirm_col2 = st.columns(2)
                with confirm_col1:
                    if st.button("✅ Yes, proceed", key=f"confirm_yes_{collection}"):
                        st.session_state[f"show_full_confirm_{collection}"] = False
                        with st.spinner("Running full ingestion — this may take a while..."):
                            try:
                                from src.embeddings.gemini_embedder import GeminiEmbedder
                                from src.ingestion.sync_manager import SyncManager
                                from src.vector_db.indexer import ArticleIndexer

                                async def _full_ingest() -> dict:
                                    embedder = GeminiEmbedder()
                                    indexer = ArticleIndexer(embedder=embedder, qdrant=qdrant)

                                    async def on_chunks(chunks: list) -> None:
                                        await indexer.index_chunks(chunks)

                                    mgr = SyncManager(on_chunks=on_chunks)
                                    return await mgr.full_ingest()

                                stats = run_async(_full_ingest())
                                st.success(
                                    f"Ingested **{stats['articles']}** article(s), "
                                    f"**{stats['chunks']}** chunk(s)"
                                )
                            except Exception as exc:
                                st.error(f"Ingestion failed: {exc}")
                with confirm_col2:
                    if st.button("❌ Cancel", key=f"confirm_no_{collection}"):
                        st.session_state[f"show_full_confirm_{collection}"] = False
                        st.rerun()

        st.divider()

    # --- Browse points ---
    st.markdown("#### 🔎 Browse Points")

    # Pagination state
    offset_key = f"kb_offset_{collection}"
    page_key = f"kb_page_{collection}"
    page_size = 20

    if offset_key not in st.session_state:
        st.session_state[offset_key] = None
        st.session_state[page_key] = 0

    try:
        points, next_offset = run_async(
            qdrant.scroll_points(collection, limit=page_size, offset=st.session_state[offset_key])
        )
    except Exception as exc:
        st.error(f"Failed to scroll points: {exc}")
        st.stop()

    if not points:
        st.info("No points in this collection.")
    else:
        rows = []
        for pt in points:
            payload = pt.payload or {}
            rows.append(
                {
                    "ID": str(pt.id)[:12] + "…",
                    "Title": payload.get("article_title", "—"),
                    "Chunk #": payload.get("chunk_index", "—"),
                    "Text Preview": (payload.get("text", "") or "")[:150],
                    "Language": payload.get("language", "—"),
                    "Source": payload.get("source", "docs"),
                }
            )

        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID": st.column_config.TextColumn("ID", width="small"),
                "Title": st.column_config.TextColumn("Title", width="medium"),
                "Chunk #": st.column_config.NumberColumn("Chunk #", width="small"),
                "Text Preview": st.column_config.TextColumn("Preview", width="large"),
                "Language": st.column_config.TextColumn("Lang", width="small"),
                "Source": st.column_config.TextColumn("Source", width="small"),
            },
        )

        # Pagination controls
        nav_col1, nav_col2, nav_col3 = st.columns([1, 3, 1])
        with nav_col1:
            if st.session_state[page_key] > 0:
                if st.button("⬅️ Previous", key=f"prev_{collection}"):
                    st.session_state[offset_key] = None
                    st.session_state[page_key] = 0
                    st.rerun()
        with nav_col2:
            st.markdown(
                f"<div style='text-align:center; color:#6b7280; padding-top:8px;'>"
                f"Page {st.session_state[page_key] + 1} &bull; "
                f"Showing {len(points)} point(s)"
                f"</div>",
                unsafe_allow_html=True,
            )
        with nav_col3:
            if next_offset is not None:
                if st.button("Next ➡️", key=f"next_{collection}"):
                    st.session_state[offset_key] = next_offset
                    st.session_state[page_key] += 1
                    st.rerun()

    st.divider()

    # --- Delete point ---
    with st.expander("🗑️ Delete a Point"):
        del_col1, del_col2 = st.columns([3, 1])
        with del_col1:
            point_id_to_delete = st.text_input(
                "Point ID",
                placeholder="Paste the full point UUID here",
                key=f"del_input_{collection}",
                label_visibility="collapsed",
            )
        with del_col2:
            if st.button(
                "Delete Point",
                type="secondary",
                key=f"delete_point_{collection}",
                use_container_width=True,
            ) and point_id_to_delete:
                try:
                    run_async(qdrant.delete_points_by_ids(collection, [point_id_to_delete]))
                    st.success(f"Deleted point `{point_id_to_delete}`")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Delete failed: {exc}")


with tab_docs:
    _render_collection(DOCS_COLLECTION)

with tab_memory:
    _render_collection(MEMORY_COLLECTION)

# --- Sidebar ---
with st.sidebar:
    st.markdown("---")
    st.markdown(
        "**DataTruck Admin** v1.0\n\n"
        "AI-powered support bot management console."
    )
