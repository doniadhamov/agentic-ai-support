"""Upload page — ingest PDF, DOCX, TXT files into the knowledge base."""

from __future__ import annotations

import streamlit as st

from src.admin.dashboard.utils import run_async
from src.admin.file_ingest import ingest_file
from src.ingestion.file_parser import SUPPORTED_EXTENSIONS, parse_file

st.set_page_config(page_title="Upload — DataTruck Admin", layout="wide")
st.title("Upload Documents")

st.markdown(
    f"Upload files to ingest into the knowledge base. "
    f"Supported formats: **{', '.join(sorted(SUPPORTED_EXTENSIONS))}**"
)

uploaded_file = st.file_uploader(
    "Choose a file",
    type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
)

if uploaded_file is not None:
    content = uploaded_file.read()
    filename = uploaded_file.name

    st.write(f"**File:** {filename} ({len(content):,} bytes)")

    # Preview extracted text
    with st.expander("Preview extracted text", expanded=True):
        try:
            blocks = parse_file(filename, content)
            if blocks:
                preview_text = "\n\n".join(b.text or "" for b in blocks if b.text)
                st.text_area(
                    "Extracted content",
                    value=preview_text[:2000] + ("..." if len(preview_text) > 2000 else ""),
                    height=300,
                    disabled=True,
                )
                st.info(f"{len(blocks)} content block(s) extracted")
            else:
                st.warning("No content could be extracted from this file.")
        except Exception as exc:
            st.error(f"Failed to parse file: {exc}")

    # Ingest button
    if st.button("Ingest into Knowledge Base", type="primary"):
        with st.spinner("Parsing, chunking, embedding, and indexing..."):
            try:
                result = run_async(ingest_file(filename, content))
                st.success(
                    f"Successfully ingested **{result.filename}**\n\n"
                    f"- Article ID: `{result.article_id}`\n"
                    f"- Chunks created: **{result.chunks}**"
                )
            except Exception as exc:
                st.error(f"Ingestion failed: {exc}")
