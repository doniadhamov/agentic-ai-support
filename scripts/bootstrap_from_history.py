"""Bootstrap knowledge from historical .telegram_chat_history/*.docx conversations.

Reads exported Telegram chat conversations, extracts Q&A pairs via Haiku,
stores them in Qdrant datatruck_memory, and seeds episodic + procedural memory
in LangGraph Store.

Usage::

    uv run python scripts/bootstrap_from_history.py
    uv run python scripts/bootstrap_from_history.py --dry-run
    uv run python scripts/bootstrap_from_history.py --file "Account Datatruck Artel Logistics.docx"
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HISTORY_DIR = Path(__file__).resolve().parent.parent / ".telegram_chat_history"

# Pattern to split a docx into individual messages.
# Typical format: "Name, [DD.MM.YYYY HH:MM]\nMessage text"
_MSG_PATTERN = re.compile(
    r"^(.+?),\s*\[(\d{1,2}\.\d{1,2}\.\d{4})\s+(\d{1,2}:\d{2})\]\s*\n(.*?)(?=\n.+?,\s*\[\d|\Z)",
    re.MULTILINE | re.DOTALL,
)

# Heuristics for identifying support conversations worth extracting.
_QUESTION_SIGNALS = re.compile(
    r"\?|how\s+(do|to|can)|что|как|где|почему|qanday|qayerda|nima|yordam",
    re.IGNORECASE,
)

_RESOLUTION_SIGNALS = re.compile(
    r"(go to|navigate|click|select|open|step\s+\d|settings|page|menu|"
    r"перейди|нажми|откройте|настройки|"
    r"bosing|tanlang|ochish|sozlamalar)",
    re.IGNORECASE,
)


def _read_docx(path: Path) -> str:
    """Extract plain text from a .docx file."""
    try:
        import docx
    except ImportError:
        logger.error("python-docx is required: uv pip install python-docx")
        sys.exit(1)

    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _parse_messages(text: str) -> list[dict]:
    """Parse exported Telegram chat text into structured messages."""
    messages = []
    for match in _MSG_PATTERN.finditer(text):
        username = match.group(1).strip()
        date_str = match.group(2)
        time_str = match.group(3)
        body = match.group(4).strip()
        if body:
            messages.append(
                {
                    "username": username,
                    "text": body,
                    "source": "telegram",
                    "timestamp": f"{date_str} {time_str}",
                }
            )
    return messages


def _extract_conversation_segments(messages: list[dict]) -> list[list[dict]]:
    """Split a long chat into conversation segments around Q&A exchanges.

    Looks for sequences where a question is followed by a resolution-like
    response within a reasonable window.
    """
    segments: list[list[dict]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if _QUESTION_SIGNALS.search(msg["text"]):
            # Found a potential question — collect the next few messages
            segment = [msg]
            for j in range(i + 1, min(i + 15, len(messages))):
                segment.append(messages[j])
                # Check if we hit a resolution
                if _RESOLUTION_SIGNALS.search(messages[j]["text"]):
                    # Include a few more messages after resolution
                    for k in range(j + 1, min(j + 3, len(messages))):
                        segment.append(messages[k])
                    break
            if len(segment) >= 2:
                segments.append(segment)
            i += len(segment)
        else:
            i += 1
    return segments


async def _summarize_segment(
    summarizer,
    segment: list[dict],
) -> dict | None:
    """Use TicketSummarizer to extract Q&A from a conversation segment."""
    try:
        result = await summarizer.summarize(segment)
        if result.get("question") and result.get("answer"):
            return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to summarize segment: {}", exc)
    return None


async def bootstrap(
    dry_run: bool = False,
    file_filter: str | None = None,
) -> dict:
    """Run the bootstrap process.

    Args:
        dry_run: If True, extract but don't store.
        file_filter: Optional filename to process only one file.

    Returns:
        Stats dict with files_processed, segments_found, qa_stored.
    """
    from src.agent.ticket_summarizer import TicketSummarizer
    from src.config.settings import get_settings
    from src.embeddings.gemini_embedder import GeminiEmbedder
    from src.memory.approved_memory import ApprovedMemory
    from src.memory.memory_schemas import ApprovedAnswer
    from src.vector_db.qdrant_client import get_qdrant_client

    settings = get_settings()
    summarizer = TicketSummarizer()
    embedder = GeminiEmbedder()
    qdrant = get_qdrant_client()
    memory = ApprovedMemory(embedder=embedder, qdrant=qdrant)

    # Initialize LangGraph Store for episodic + procedural memory
    store = None
    episode_recorder = None
    example_selector = None

    if settings.database_url:
        from langgraph.store.postgres import AsyncPostgresStore

        from src.learning.episode_recorder import EpisodeRecorder
        from src.learning.example_selector import ExampleSelector

        store_cm = AsyncPostgresStore.from_conn_string(settings.database_url_psycopg)
        store = await store_cm.__aenter__()
        await store.setup()
        episode_recorder = EpisodeRecorder(store)
        example_selector = ExampleSelector(store)

        # Seed default procedural examples
        await example_selector.seed_default_examples()
        logger.info("LangGraph Store initialized for bootstrap")

    if not HISTORY_DIR.exists():
        logger.error("History directory not found: {}", HISTORY_DIR)
        return {"files_processed": 0, "segments_found": 0, "qa_stored": 0}

    docx_files = sorted(HISTORY_DIR.glob("*.docx"))
    if file_filter:
        docx_files = [f for f in docx_files if file_filter in f.name]

    if not docx_files:
        logger.warning("No .docx files found in {}", HISTORY_DIR)
        return {"files_processed": 0, "segments_found": 0, "qa_stored": 0}

    stats = {"files_processed": 0, "segments_found": 0, "qa_stored": 0}

    for docx_path in docx_files:
        logger.info("Processing: {}", docx_path.name)
        text = _read_docx(docx_path)
        messages = _parse_messages(text)
        logger.info("  Parsed {} messages", len(messages))

        segments = _extract_conversation_segments(messages)
        logger.info("  Found {} conversation segments", len(segments))
        stats["segments_found"] += len(segments)

        for idx, segment in enumerate(segments):
            summary = await _summarize_segment(summarizer, segment)
            if summary is None:
                continue

            question = summary["question"]
            answer = summary["answer"]
            tags = summary.get("tags", [])

            logger.info(
                "  Segment {}: Q={!r}",
                idx + 1,
                question[:60],
            )

            if dry_run:
                logger.info("  [DRY RUN] Would store: {!r}", question[:80])
                stats["qa_stored"] += 1
                continue

            # Store Q&A in Qdrant memory
            try:
                await memory.store(
                    ApprovedAnswer(
                        question=question,
                        answer=answer,
                    )
                )
                stats["qa_stored"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("  Failed to store Q&A: {}", exc)
                continue

            # Record episode if store is available
            if episode_recorder:
                try:
                    await episode_recorder.record_episode(
                        ticket_id=0,  # no real ticket
                        group_id=0,
                        user_id=0,
                        subject=question[:80],
                        question=question,
                        answer=answer,
                        action="answer",
                        ticket_action="create_new",
                        messages=segment,
                        tags=tags,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("  Failed to record episode: {}", exc)

        stats["files_processed"] += 1

    # Cleanup store
    if store is not None:
        await store_cm.__aexit__(None, None, None)

    logger.info(
        "Bootstrap complete: {} files, {} segments, {} Q&A stored",
        stats["files_processed"],
        stats["segments_found"],
        stats["qa_stored"],
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap knowledge from historical Telegram chat exports"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract Q&A pairs but don't store them",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Process only files matching this substring",
    )
    args = parser.parse_args()

    asyncio.run(bootstrap(dry_run=args.dry_run, file_filter=args.file))


if __name__ == "__main__":
    main()
