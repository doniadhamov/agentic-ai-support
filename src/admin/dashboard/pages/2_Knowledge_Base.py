"""Knowledge Base page — 5 tabs: Documentation, Learned Q&A, Quick Add, Import from Zendesk, Upload."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.admin.dashboard.styles import SHARED_CSS, sidebar_branding
from src.admin.dashboard.utils import run_async
from src.vector_db.collections import DOCS_COLLECTION, MEMORY_COLLECTION
from src.vector_db.qdrant_client import get_qdrant_client

st.set_page_config(page_title="Knowledge Base — DataTruck Admin", layout="wide")
st.markdown(SHARED_CSS, unsafe_allow_html=True)

qdrant = get_qdrant_client()


# ============================================================================
# Helper functions (must be defined before use)
# ============================================================================


def _browse_collection(collection: str, key_prefix: str) -> None:
    """Paginated point browser for a Qdrant collection."""
    offset_key = f"kb_offset_{key_prefix}"
    page_key = f"kb_page_{key_prefix}"
    page_size = 20

    if offset_key not in st.session_state:
        st.session_state[offset_key] = None
        st.session_state[page_key] = 0

    try:
        points, next_offset = run_async(
            qdrant.scroll_points(collection, limit=page_size, offset=st.session_state[offset_key])
        )
    except Exception as exc:
        st.error(f"Failed to browse: {exc}")
        return

    if not points:
        st.info("No points in this collection.")
        return

    rows = []
    for pt in points:
        payload = pt.payload or {}
        rows.append(
            {
                "ID": str(pt.id)[:12] + "...",
                "Title": payload.get("article_title", "—"),
                "Chunk #": payload.get("chunk_index", "—"),
                "Preview": (payload.get("text", "") or "")[:150],
                "Language": payload.get("language", "—"),
                "Source": payload.get("source_type", payload.get("source", "docs")),
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "ID": st.column_config.TextColumn("ID", width="small"),
            "Title": st.column_config.TextColumn("Title", width="medium"),
            "Chunk #": st.column_config.NumberColumn("Chunk", width="small"),
            "Preview": st.column_config.TextColumn("Preview", width="large"),
            "Language": st.column_config.TextColumn("Lang", width="small"),
            "Source": st.column_config.TextColumn("Source", width="small"),
        },
    )

    nav1, nav2, nav3 = st.columns([1, 3, 1])
    with nav1:
        if st.session_state[page_key] > 0:  # noqa: SIM102
            if st.button("Previous", key=f"prev_{key_prefix}"):
                st.session_state[offset_key] = None
                st.session_state[page_key] = 0
                st.rerun()
    with nav2:
        st.caption(f"Page {st.session_state[page_key] + 1} — {len(points)} point(s)")
    with nav3:
        if next_offset is not None:  # noqa: SIM102
            if st.button("Next", key=f"next_{key_prefix}"):
                st.session_state[offset_key] = next_offset
                st.session_state[page_key] += 1
                st.rerun()

    # Delete point
    with st.expander("Delete a Point"):
        dc1, dc2 = st.columns([3, 1])
        with dc1:
            point_id_del = st.text_input(
                "Point ID",
                placeholder="Full point UUID",
                key=f"del_{key_prefix}",
                label_visibility="collapsed",
            )
        with dc2:
            if st.button("Delete", key=f"del_btn_{key_prefix}") and point_id_del:
                try:
                    run_async(qdrant.delete_points_by_ids(collection, [point_id_del]))
                    st.success(f"Deleted `{point_id_del}`")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Delete failed: {exc}")


def _browse_memory_collection(search_text: str = "") -> None:
    """Browse the learned Q&A memory collection with optional search."""
    page_size = 20
    offset_key = "mem_offset"
    page_key = "mem_page"

    if offset_key not in st.session_state:
        st.session_state[offset_key] = None
        st.session_state[page_key] = 0

    try:
        points, next_offset = run_async(
            qdrant.scroll_points(
                MEMORY_COLLECTION, limit=page_size, offset=st.session_state[offset_key]
            )
        )
    except Exception as exc:
        st.error(f"Failed to browse memory: {exc}")
        return

    if not points:
        st.info("No learned Q&A entries yet.")
        return

    # Filter by search text if provided
    if search_text:
        search_lower = search_text.lower()
        points = [
            pt
            for pt in points
            if search_lower in (pt.payload or {}).get("question", "").lower()
            or search_lower in (pt.payload or {}).get("text", "").lower()
        ]

    rows = []
    for pt in points:
        payload = pt.payload or {}
        rows.append(
            {
                "ID": str(pt.id)[:12] + "...",
                "Question": payload.get("question", "—"),
                "Answer Preview": (payload.get("answer", "") or payload.get("text", ""))[:150],
                "Language": payload.get("language", "—"),
                "Source": payload.get("source_type", "learned"),
            }
        )

    if not rows:
        st.info("No entries match your search.")
        return

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "ID": st.column_config.TextColumn("ID", width="small"),
            "Question": st.column_config.TextColumn("Question", width="large"),
            "Answer Preview": st.column_config.TextColumn("Answer", width="large"),
            "Language": st.column_config.TextColumn("Lang", width="small"),
            "Source": st.column_config.TextColumn("Source", width="small"),
        },
    )

    nav1, nav2, nav3 = st.columns([1, 3, 1])
    with nav1:
        if st.session_state[page_key] > 0:  # noqa: SIM102
            if st.button("Previous", key="prev_mem"):
                st.session_state[offset_key] = None
                st.session_state[page_key] = 0
                st.rerun()
    with nav2:
        st.caption(f"Page {st.session_state[page_key] + 1} — {len(points)} entry(ies)")
    with nav3:
        if next_offset is not None:  # noqa: SIM102
            if st.button("Next", key="next_mem"):
                st.session_state[offset_key] = next_offset
                st.session_state[page_key] += 1
                st.rerun()

    # Delete entry
    with st.expander("Delete a Memory Entry"):
        dc1, dc2 = st.columns([3, 1])
        with dc1:
            mem_id_del = st.text_input(
                "Point ID",
                placeholder="Full point UUID",
                key="del_mem_id",
                label_visibility="collapsed",
            )
        with dc2:
            if st.button("Delete", key="del_mem_btn") and mem_id_del:
                try:
                    run_async(qdrant.delete_points_by_ids(MEMORY_COLLECTION, [mem_id_del]))
                    st.success(f"Deleted `{mem_id_del}`")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Delete failed: {exc}")


def _store_qa_pair(question: str, answer: str, language: str, ticket_id: int = 0) -> str:
    """Embed and store a Q&A pair in memory. Returns point_id."""
    from src.embeddings.gemini_embedder import GeminiEmbedder
    from src.memory.approved_memory import ApprovedMemory
    from src.memory.memory_schemas import ApprovedAnswer

    embedder = GeminiEmbedder()
    memory = ApprovedMemory(embedder=embedder, qdrant=qdrant)
    return run_async(
        memory.store(
            ApprovedAnswer(
                question=question,
                answer=answer,
                language=language,
                ticket_id=ticket_id,
            )
        )
    )


def _fetch_and_extract_tickets(ticket_ids: list[int]) -> None:
    """Fetch ticket comments from Zendesk and extract Q&A pairs."""
    with st.spinner(f"Fetching {len(ticket_ids)} ticket(s) from Zendesk..."):
        try:
            from src.agent.ticket_summarizer import TicketSummarizer
            from src.escalation.ticket_client import ZendeskTicketClient

            client = ZendeskTicketClient()
            summarizer = TicketSummarizer()
            extracted_pairs: list[dict] = []

            for tid in ticket_ids:
                try:
                    ticket = run_async(client.get_ticket(tid))
                    comments = run_async(client.get_ticket_comments(tid))
                    subject = ticket.get("subject", f"Ticket #{tid}")

                    messages = []
                    for c in comments:
                        body = c.get("body", "").strip()
                        is_public = c.get("public", True)
                        if not body or not is_public:
                            continue
                        author_id = c.get("author_id", 0)
                        messages.append(
                            {
                                "username": f"User_{author_id}",
                                "text": body,
                                "source": "telegram",
                            }
                        )

                    if len(messages) < 2:
                        continue

                    result = run_async(summarizer.summarize(messages))
                    if result.get("question") and result.get("answer"):
                        extracted_pairs.append(
                            {
                                "ticket_id": tid,
                                "subject": subject,
                                "question": result["question"],
                                "answer": result["answer"],
                                "tags": result.get("tags", []),
                                "language": "en",
                            }
                        )
                except Exception as exc:
                    st.warning(f"Failed to process ticket #{tid}: {exc}")

            run_async(client.close())

            if extracted_pairs:
                st.session_state["extracted_qa_pairs"] = extracted_pairs
                st.success(f"Extracted {len(extracted_pairs)} Q&A pair(s). Review below.")
                st.rerun()
            else:
                st.warning("No Q&A pairs could be extracted from the selected tickets.")
        except Exception as exc:
            st.error(f"Failed to fetch tickets: {exc}")


def _render_review_screen() -> None:
    """Render the shared review screen for extracted Q&A pairs."""
    if "extracted_qa_pairs" not in st.session_state or not st.session_state["extracted_qa_pairs"]:
        return

    st.divider()
    st.markdown("#### Review Extracted Q&A Pairs")

    pairs = st.session_state["extracted_qa_pairs"]
    approved_count = sum(1 for p in pairs if p.get("_status") == "approved")
    remaining = [p for p in pairs if p.get("_status") not in ("approved", "rejected")]

    if approved_count > 0:
        st.success(f"{approved_count} Q&A pair(s) already approved and stored.")

    for i, pair in enumerate(pairs):
        if pair.get("_status") in ("approved", "rejected"):
            continue

        with st.container():
            st.markdown(f"**Ticket #{pair.get('ticket_id', '?')}**: {pair.get('subject', '')}")

            eq = st.text_input("Question", value=pair["question"], key=f"qa_q_{i}")
            ea = st.text_area("Answer", value=pair["answer"], height=120, key=f"qa_a_{i}")
            el = st.selectbox("Language", ["en", "ru", "uz"], index=0, key=f"qa_l_{i}")

            bc1, bc2, _bc3 = st.columns(3)
            with bc1:
                if st.button("Approve", type="primary", key=f"approve_{i}"):
                    with st.spinner("Storing..."):
                        try:
                            _store_qa_pair(eq.strip(), ea.strip(), el, pair.get("ticket_id", 0))
                            st.session_state["extracted_qa_pairs"][i]["_status"] = "approved"
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed: {exc}")
            with bc2:
                if st.button("Reject", key=f"reject_{i}"):
                    st.session_state["extracted_qa_pairs"][i]["_status"] = "rejected"
                    st.rerun()

            st.markdown("---")

    # Approve all remaining
    if len(remaining) > 1:  # noqa: SIM102
        if st.button("Approve All Remaining", type="primary", key="approve_all"):
            with st.spinner(f"Storing {len(remaining)} pairs..."):
                for j, p in enumerate(pairs):
                    if p.get("_status") in ("approved", "rejected"):
                        continue
                    try:
                        _store_qa_pair(
                            p["question"],
                            p["answer"],
                            p.get("language", "en"),
                            p.get("ticket_id", 0),
                        )
                        st.session_state["extracted_qa_pairs"][j]["_status"] = "approved"
                    except Exception:
                        pass
            st.rerun()


# ============================================================================
# Page content
# ============================================================================

st.title("📚 Knowledge Base")
st.caption(
    "Manage documentation, learned knowledge, and import new knowledge from multiple sources."
)

# --- Top stats ---
docs_count = 0
memory_count = 0
try:
    docs_count = run_async(qdrant.count_points(DOCS_COLLECTION))
    memory_count = run_async(qdrant.count_points(MEMORY_COLLECTION))
except Exception:
    pass

c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Doc Chunks", f"{docs_count:,}")
with c2:
    st.metric("Learned Q&A", f"{memory_count:,}")
with c3:
    st.metric("Total Points", f"{docs_count + memory_count:,}")

st.markdown("")

# ============================================================================
# TABS
# ============================================================================
tab_docs, tab_memory, tab_quick, tab_zendesk, tab_upload = st.tabs(
    ["📄 Documentation", "🧠 Learned Q&A", "➕ Quick Add", "📥 Import from Zendesk", "📤 Upload"]
)

# --- TAB 1: Documentation ---
with tab_docs:
    st.markdown("#### Documentation Collection")

    st.markdown("**Zendesk Sync**")
    sync_col1, sync_col2, sync_col3 = st.columns([2, 2, 3])

    with sync_col1:
        if st.button(
            "⚡ Delta Sync (24h)", type="primary", use_container_width=True, key="docs_delta"
        ):
            with st.spinner("Running delta sync..."):
                try:
                    from src.embeddings.gemini_embedder import GeminiEmbedder
                    from src.ingestion.sync_manager import SyncManager
                    from src.vector_db.indexer import ArticleIndexer

                    async def _delta_sync() -> dict:
                        from src.vector_db.collections import create_collections_if_not_exist

                        await create_collections_if_not_exist(qdrant._client)
                        embedder = GeminiEmbedder()
                        indexer = ArticleIndexer(embedder=embedder, qdrant=qdrant)
                        mgr = SyncManager(on_chunks=lambda chunks: indexer.index_chunks(chunks))
                        return await mgr.delta_sync()

                    s = run_async(_delta_sync())
                    st.success(f"Synced **{s['articles']}** article(s), **{s['chunks']}** chunk(s)")
                except Exception as exc:
                    st.error(f"Sync failed: {exc}")

    with sync_col2:
        if st.button(
            "🔃 Full Re-ingest", type="secondary", use_container_width=True, key="docs_full"
        ):
            st.session_state["show_full_confirm"] = True

    with sync_col3:
        if st.session_state.get("show_full_confirm"):
            st.warning("This will re-ingest all Zendesk articles. May take several minutes.")
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("Yes, proceed", key="confirm_full_yes"):
                    st.session_state["show_full_confirm"] = False
                    with st.spinner("Running full ingestion..."):
                        try:
                            from src.embeddings.gemini_embedder import GeminiEmbedder
                            from src.ingestion.sync_manager import SyncManager
                            from src.vector_db.indexer import ArticleIndexer

                            async def _full_ingest() -> dict:
                                from src.vector_db.collections import (
                                    create_collections_if_not_exist,
                                )

                                await create_collections_if_not_exist(qdrant._client)
                                embedder = GeminiEmbedder()
                                indexer = ArticleIndexer(embedder=embedder, qdrant=qdrant)
                                mgr = SyncManager(
                                    on_chunks=lambda chunks: indexer.index_chunks(chunks)
                                )
                                return await mgr.full_ingest()

                            s = run_async(_full_ingest())
                            st.success(
                                f"Ingested **{s['articles']}** article(s), **{s['chunks']}** chunk(s)"
                            )
                        except Exception as exc:
                            st.error(f"Ingestion failed: {exc}")
                    st.rerun()
            with cc2:
                if st.button("Cancel", key="confirm_full_no"):
                    st.session_state["show_full_confirm"] = False
                    st.rerun()

    st.divider()
    st.markdown("**Browse Documentation Points**")
    _browse_collection(DOCS_COLLECTION, "docs")

# --- TAB 2: Learned Q&A ---
with tab_memory:
    st.markdown("#### Learned Q&A Collection")
    st.caption("Q&A pairs extracted from resolved tickets and manual additions.")

    mem_search = st.text_input("Search", placeholder="Search by question text...", key="mem_search")
    _browse_memory_collection(mem_search)

# --- TAB 3: Quick Add ---
with tab_quick:
    st.markdown("#### Quick Add Q&A")
    st.caption("Manually add a Q&A pair. No review step — you wrote it yourself.")

    with st.form("quick_add_form", clear_on_submit=True):
        qa_question = st.text_input("Question", placeholder="How do I change load status?")
        qa_answer = st.text_area(
            "Answer",
            placeholder="Go to Settings > Load Management > select the load...",
            height=200,
        )
        qa_language = st.selectbox("Language", ["en", "ru", "uz"], index=0)
        submitted = st.form_submit_button("Save to Memory", type="primary")

        if submitted:
            if not qa_question.strip() or not qa_answer.strip():
                st.error("Both question and answer are required.")
            else:
                with st.spinner("Embedding and storing..."):
                    try:
                        point_id = _store_qa_pair(
                            qa_question.strip(), qa_answer.strip(), qa_language
                        )
                        st.success(f"Stored Q&A pair (point_id: `{point_id[:12]}...`)")
                    except Exception as exc:
                        st.error(f"Failed to store: {exc}")

# --- TAB 4: Import from Zendesk ---
with tab_zendesk:
    st.markdown("#### Import Q&A from Zendesk Tickets")
    st.caption("Fetch solved tickets, extract Q&A pairs with AI, review and approve them.")

    import_mode = st.radio(
        "Import mode",
        ["Single ticket", "Ticket range"],
        horizontal=True,
        key="import_mode",
    )

    if import_mode == "Single ticket":
        ticket_id_input = st.number_input("Ticket ID", min_value=1, step=1, key="single_ticket_id")
        if st.button("Fetch", type="primary", key="fetch_single") and ticket_id_input:
            _fetch_and_extract_tickets([int(ticket_id_input)])

    elif import_mode == "Ticket range":
        rc1, rc2, rc3 = st.columns([2, 2, 1])
        with rc1:
            range_from = st.number_input("From ID", min_value=1, step=1, key="range_from")
        with rc2:
            range_to = st.number_input("To ID", min_value=1, step=1, key="range_to")
        with rc3:
            st.markdown("<br>", unsafe_allow_html=True)
            if (
                st.button("Fetch", type="primary", key="fetch_range")
                and range_from
                and range_to
                and range_to >= range_from
            ):
                _fetch_and_extract_tickets(list(range(int(range_from), int(range_to) + 1)))

    _render_review_screen()

# --- TAB 5: Upload ---
with tab_upload:
    st.markdown("#### Upload Documents")
    st.caption("Ingest files into the documentation knowledge base.")

    from src.ingestion.file_parser import SUPPORTED_EXTENSIONS

    formats_html = " ".join(
        f'<span style="display:inline-block;padding:4px 12px;border-radius:20px;'
        f'font-size:0.8rem;font-weight:600;margin:2px 4px;background:#f0f4ff;color:#4338ca;">'
        f"{ext}</span>"
        for ext in sorted(SUPPORTED_EXTENSIONS)
    )
    st.markdown(f"**Supported formats:** {formats_html}", unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        "Choose a file",
        type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
        help="Drag and drop or click to browse.",
        key="doc_upload",
    )

    if uploaded_file is not None:
        content = uploaded_file.read()
        filename = uploaded_file.name

        ic1, ic2, ic3 = st.columns(3)
        with ic1:
            st.metric("Filename", filename)
        with ic2:
            size_kb = len(content) / 1024
            st.metric(
                "File Size", f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            )
        with ic3:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else "?"
            st.metric("Format", ext.upper())

        with st.expander("Preview Extracted Text", expanded=False):
            try:
                from src.ingestion.file_parser import parse_file

                blocks = parse_file(filename, content)
                if blocks:
                    preview = "\n\n".join(b.text or "" for b in blocks if b.text)
                    st.text_area(
                        "preview",
                        value=preview[:3000] + ("..." if len(preview) > 3000 else ""),
                        height=250,
                        disabled=True,
                        label_visibility="collapsed",
                    )
                    st.info(f"**{len(blocks)}** block(s), **{len(preview):,}** characters")
                else:
                    st.warning("No content extracted.")
            except Exception as exc:
                st.error(f"Parse error: {exc}")

        if st.button("Ingest into Knowledge Base", type="primary", key="ingest_btn"):
            with st.spinner("Parsing, chunking, embedding, and indexing..."):
                try:
                    from src.admin.file_ingest import ingest_file

                    result = run_async(ingest_file(filename, content))
                    st.success(
                        f"Ingested **{result.filename}** — "
                        f"article_id=`{result.article_id}`, **{result.chunks}** chunks"
                    )
                    st.balloons()
                except Exception as exc:
                    st.error(f"Ingestion failed: {exc}")

    st.divider()

    # Conversation file upload for Q&A extraction
    st.markdown("#### Upload Conversation File")
    st.caption("Upload a conversation transcript (PDF/DOCX/TXT) to extract Q&A pairs.")

    conv_file = st.file_uploader(
        "Choose a conversation file",
        type=["pdf", "docx", "txt"],
        help="Drag and drop a ticket conversation export.",
        key="conv_upload",
    )

    if conv_file is not None:
        conv_content = conv_file.read()
        conv_filename = conv_file.name

        if st.button("Extract Q&A from conversation", type="primary", key="extract_conv"):
            with st.spinner("Parsing and extracting Q&A with AI..."):
                try:
                    from src.ingestion.file_parser import parse_file

                    blocks = parse_file(conv_filename, conv_content)
                    conv_text = "\n\n".join(b.text or "" for b in blocks if b.text)
                    if not conv_text.strip():
                        st.error("No text content extracted from the file.")
                    else:
                        from src.agent.ticket_summarizer import TicketSummarizer

                        summarizer = TicketSummarizer()
                        messages = [{"username": "User", "text": conv_text, "source": "telegram"}]
                        result = run_async(summarizer.summarize(messages))
                        if result.get("question") and result.get("answer"):
                            st.session_state["extracted_qa_pairs"] = [
                                {
                                    "ticket_id": 0,
                                    "subject": conv_filename,
                                    "question": result["question"],
                                    "answer": result["answer"],
                                    "language": "en",
                                }
                            ]
                            st.success(
                                "Extracted 1 Q&A pair. Switch to 'Import from Zendesk' tab to review."
                            )
                        else:
                            st.warning("Could not extract a Q&A pair from this conversation.")
                except Exception as exc:
                    st.error(f"Extraction failed: {exc}")


sidebar_branding()
