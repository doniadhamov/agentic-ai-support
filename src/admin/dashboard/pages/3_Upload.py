"""Upload page — ingest PDF, DOCX, TXT files into the knowledge base."""

from __future__ import annotations

import streamlit as st

from src.admin.dashboard.utils import run_async
from src.admin.file_ingest import ingest_file
from src.ingestion.file_parser import SUPPORTED_EXTENSIONS, parse_file

st.set_page_config(page_title="Upload — DataTruck Admin", layout="wide")

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

.upload-zone {
    border: 2px dashed #cbd5e1;
    border-radius: 12px;
    padding: 32px;
    text-align: center;
    background: #fafbfd;
    transition: border-color 0.2s;
}
.upload-zone:hover {
    border-color: #667eea;
}

.file-info-card {
    background: white;
    border: 1px solid #e8ecf1;
    border-radius: 10px;
    padding: 20px;
    margin: 16px 0;
}

.success-card {
    background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%);
    border-radius: 12px;
    padding: 24px;
    margin: 16px 0;
}
.success-card h4 {
    color: #065f46;
    margin: 0 0 12px 0;
}
.success-card p {
    color: #047857;
    margin: 4px 0;
}

.format-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    margin: 2px 4px;
    background: #f0f4ff;
    color: #4338ca;
}
</style>
""",
    unsafe_allow_html=True,
)

# --- Page header ---
st.title("📄 Upload Documents")
st.caption("Ingest files into the knowledge base. Files are parsed, chunked, embedded, and indexed automatically.")

# --- Supported formats ---
formats_html = " ".join(
    f'<span class="format-badge">{ext}</span>' for ext in sorted(SUPPORTED_EXTENSIONS)
)
st.markdown(f"**Supported formats:** {formats_html}", unsafe_allow_html=True)

st.markdown("")

# --- Upload area ---
col_upload, col_info = st.columns([3, 2])

with col_upload:
    uploaded_file = st.file_uploader(
        "Choose a file",
        type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
        help="Drag and drop a file here or click to browse.",
    )

with col_info:
    st.markdown(
        """
        **How it works:**
        1. **Parse** — extract text from your document
        2. **Chunk** — split into manageable segments
        3. **Embed** — generate vector embeddings via Gemini
        4. **Index** — store in Qdrant for retrieval

        Documents get a deterministic article ID (10M+ offset)
        to avoid collision with Zendesk article IDs.
        """
    )

if uploaded_file is not None:
    content = uploaded_file.read()
    filename = uploaded_file.name

    st.divider()

    # --- File info ---
    info_col1, info_col2, info_col3 = st.columns(3)
    with info_col1:
        st.metric("Filename", filename)
    with info_col2:
        size_kb = len(content) / 1024
        size_display = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        st.metric("File Size", size_display)
    with info_col3:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
        st.metric("Format", ext.upper())

    st.markdown("")

    # --- Preview ---
    with st.expander("📋 Preview Extracted Text", expanded=True):
        try:
            blocks = parse_file(filename, content)
            if blocks:
                preview_text = "\n\n".join(b.text or "" for b in blocks if b.text)
                st.text_area(
                    "Extracted content",
                    value=preview_text[:3000] + ("…" if len(preview_text) > 3000 else ""),
                    height=300,
                    disabled=True,
                    label_visibility="collapsed",
                )

                block_col1, block_col2 = st.columns(2)
                with block_col1:
                    st.info(f"**{len(blocks)}** content block(s) extracted")
                with block_col2:
                    st.info(f"**{len(preview_text):,}** characters total")
            else:
                st.warning("No content could be extracted from this file.")
        except Exception as exc:
            st.error(f"Failed to parse file: {exc}")

    st.markdown("")

    # --- Ingest button ---
    btn_col1, btn_col2, btn_col3 = st.columns([1, 2, 1])
    with btn_col2:
        if st.button(
            "🚀 Ingest into Knowledge Base",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner("Parsing, chunking, embedding, and indexing..."):
                try:
                    result = run_async(ingest_file(filename, content))
                    st.markdown(
                        f"""<div class="success-card">
                            <h4>✅ Successfully Ingested</h4>
                            <p><strong>File:</strong> {result.filename}</p>
                            <p><strong>Article ID:</strong> <code>{result.article_id}</code></p>
                            <p><strong>Chunks created:</strong> {result.chunks}</p>
                        </div>""",
                        unsafe_allow_html=True,
                    )
                    st.balloons()
                except Exception as exc:
                    st.error(f"Ingestion failed: {exc}")

# --- Sidebar ---
with st.sidebar:
    st.markdown("---")
    st.markdown(
        "**DataTruck Admin** v1.0\n\n"
        "AI-powered support bot management console."
    )
