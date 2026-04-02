"""aiogram Router: handles incoming group and supergroup messages.

Each message is preprocessed and invoked through the LangGraph state machine.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from langgraph.graph.state import CompiledStateGraph
from loguru import logger

from src.database.repositories import (
    get_or_create_telegram_group,
    get_or_create_telegram_user,
    save_message,
)
from src.telegram.preprocessor import preprocess

router = Router(name="group_messages")

_MAX_IMAGES = 5


def _has_supported_content(message: Message) -> bool:
    """Return True if the message contains content we can process."""
    return bool(
        message.text
        or message.caption
        or message.photo
        or message.voice
        or message.audio
        or (
            message.document
            and message.document.mime_type
            and message.document.mime_type.startswith("image/")
        )
    )


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(
    message: Message,
    graph: CompiledStateGraph | None = None,
) -> None:
    """Process an incoming group message through the LangGraph state machine."""
    if not message.from_user:
        return

    if not _has_supported_content(message):
        return

    chat_id: int = message.chat.id
    user_id: int = message.from_user.id
    username: str = message.from_user.full_name or str(user_id)
    group_name: str = message.chat.title or str(chat_id)

    # Upsert group in DB and check active flag
    try:
        group = await get_or_create_telegram_group(chat_id, title=group_name)
        if not group.active:
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to check group status for chat_id={}: {}", chat_id, exc)

    # Upsert Telegram user in DB
    try:
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        tg_username = message.from_user.username or ""
        display_name = (
            f"{first_name} {last_name}".strip() or tg_username or f"telegram_user_{user_id}"
        )
        await get_or_create_telegram_user(user_id, display_name=display_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to upsert telegram_user user_id={}: {}", user_id, exc)

    log_ctx = {"group_id": chat_id, "user_id": user_id, "message_id": message.message_id}

    # --- Preprocess (download media, transcribe voice) ----------------------
    pp = await preprocess(message, message.bot)
    if not pp.is_supported:
        logger.bind(**log_ctx).debug("Unsupported or failed preprocessing, skipping")
        return

    message_text = pp.text or message.text or message.caption or ""
    images = pp.images[:_MAX_IMAGES] if pp.images else []

    reply_to_msg_id: int | None = None
    if message.reply_to_message:
        reply_to_msg_id = message.reply_to_message.message_id

    # --- Extract file info --------------------------------------------------
    file_id: str | None = None
    file_type: str | None = None
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.voice:
        file_id = message.voice.file_id
        file_type = "voice"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "voice"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"

    # --- Store ALL messages in DB (before graph — ensures complete history) --
    try:
        await save_message(
            chat_id=chat_id,
            message_id=message.message_id,
            user_id=user_id,
            username=username,
            text=message_text,
            source="telegram",
            reply_to_message_id=reply_to_msg_id,
            file_id=file_id,
            file_type=file_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).warning("Failed to store message in DB: {}", exc)

    # --- Invoke LangGraph state machine -------------------------------------
    if graph is None:
        logger.bind(**log_ctx).warning("No graph available — skipping processing")
        return

    config = {"configurable": {"thread_id": str(chat_id)}}
    try:
        await graph.ainvoke(
            {
                "raw_text": message_text,
                "images": images,
                "sender_id": str(user_id),
                "sender_name": username,
                "group_id": str(chat_id),
                "group_name": group_name,
                "telegram_message_id": message.message_id,
                "reply_to_message_id": reply_to_msg_id,
            },
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).error("Graph invocation failed: {}", exc)
