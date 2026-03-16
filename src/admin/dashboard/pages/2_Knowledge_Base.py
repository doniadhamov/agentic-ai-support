"""Knowledge Base page — browse Qdrant collections and trigger sync."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.admin.dashboard.utils import run_async
from src.vector_db.collections import DOCS_COLLECTION, MEMORY_COLLECTION
from src.vector_db.qdrant_client import get_qdrant_client

st.set_page_config(page_title="Knowledge Base — DataTruck Admin", layout="wide")
st.title("Knowledge Base")

qdrant = get_qdrant_client()

# --- Collection selector ---
collection = st.selectbox(
    "Collection",
    [DOCS_COLLECTION, MEMORY_COLLECTION],
    format_func=lambda c: f"{c}",
)

# --- Collection stats ---
try:
    info = run_async(qdrant.get_collection_info(collection))
    point_count = info.points_count or 0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Points", f"{point_count:,}")
    with col2:
        vectors_config = info.config.params.vectors
        if hasattr(vectors_config, "size"):
            st.metric("Vector Size", vectors_config.size)
        else:
            st.metric("Vector Size", "—")
    with col3:
        st.metric("Status", info.status.value if info.status else "unknown")
except Exception as exc:
    st.error(f"Failed to fetch collection info: {exc}")
    st.stop()

st.divider()

# --- Sync controls ---
st.subheader("Zendesk Sync")
col1, col2 = st.columns(2)
with col1:
    if st.button("Delta Sync (last 24h)"):
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
                st.success(f"Synced {stats['articles']} article(s), {stats['chunks']} chunk(s)")
            except Exception as exc:
                st.error(f"Sync failed: {exc}")

with col2:
    if st.button("Full Re-ingest", type="secondary"):
        confirm = st.checkbox("I confirm full re-ingestion", key="confirm_full_ingest")
        if confirm:
            with st.spinner("Running full ingestion (this may take a while)..."):
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
                        f"Ingested {stats['articles']} article(s), {stats['chunks']} chunk(s)"
                    )
                except Exception as exc:
                    st.error(f"Ingestion failed: {exc}")

st.divider()

# --- Browse points ---
st.subheader("Browse Points")

# Pagination
page_size = 20
if "kb_offset" not in st.session_state:
    st.session_state["kb_offset"] = None
    st.session_state["kb_page"] = 0

try:
    points, next_offset = run_async(
        qdrant.scroll_points(collection, limit=page_size, offset=st.session_state["kb_offset"])
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
                "ID": str(pt.id)[:12] + "...",
                "Title": payload.get("article_title", "—"),
                "Chunk": payload.get("chunk_index", "—"),
                "Text Preview": (payload.get("text", "") or "")[:200],
                "Language": payload.get("language", "—"),
                "Source": payload.get("source", "docs"),
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Pagination controls
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        st.write(f"Page {st.session_state['kb_page'] + 1}")
    with col3:
        if next_offset is not None and st.button("Next Page"):
            st.session_state["kb_offset"] = next_offset
            st.session_state["kb_page"] += 1
            st.rerun()

    # Delete point
    st.subheader("Delete Point")
    point_id_to_delete = st.text_input(
        "Point ID to delete",
        placeholder="Enter full point UUID",
    )
    if st.button("Delete", type="secondary", key="delete_point") and point_id_to_delete:
        try:
            run_async(qdrant.delete_points_by_ids(collection, [point_id_to_delete]))
            st.success(f"Deleted point {point_id_to_delete}")
            st.rerun()
        except Exception as exc:
            st.error(f"Delete failed: {exc}")
