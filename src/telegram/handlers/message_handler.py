"""aiogram Router: handles incoming group and supergroup messages.

Each message is processed immediately (no batching/debounce):
1. Preprocess (normalize media, transcribe voice)
2. Store in DB (ALL messages, regardless of category)
3. Record in GroupContext
4. Run AI pipeline
5. Sync to Zendesk via ZendeskSyncService
6. Reply to Telegram if needed
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from loguru import logger

from src.agent.agent import SupportAgent
from src.agent.schemas import AgentInput
from src.database.repositories import (
    get_or_create_telegram_group,
    get_or_create_telegram_user,
    save_message,
)
from src.escalation.sync_service import ZendeskSyncService
from src.telegram.context.context_manager import ContextManager
from src.telegram.context.group_context import MessageRecord
from src.telegram.formatter import format_reply
from src.telegram.preprocessor import preprocess

router = Router(name="group_messages")

# Maximum images to include in a single agent call
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
    agent: SupportAgent,
    context_manager: ContextManager,
    sync_service: ZendeskSyncService | None = None,
) -> None:
    """Process an incoming group message immediately (no debounce).

    Flow: preprocess → store in DB → record context → AI pipeline → Zendesk sync → reply.
    """
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

    # --- Step 1: Preprocess (download media, transcribe voice, etc.) ----------
    pp = await preprocess(message, message.bot)
    if not pp.is_supported:
        logger.bind(**log_ctx).debug("Unsupported or failed preprocessing, skipping")
        return

    message_text = pp.text or message.text or message.caption or ""
    images = pp.images[:_MAX_IMAGES] if pp.images else []

    # Get reply-to message ID if this is a reply
    reply_to_msg_id: int | None = None
    if message.reply_to_message:
        reply_to_msg_id = message.reply_to_message.message_id

    # --- Step 2: Store in DB (ALL messages, regardless of category) -----------
    try:
        await save_message(
            chat_id=chat_id,
            message_id=message.message_id,
            user_id=user_id,
            username=username,
            text=message_text,
            source="telegram",
            reply_to_message_id=reply_to_msg_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).warning("Failed to store message in DB: {}", exc)

    # --- Step 3: Record in group context --------------------------------------
    ctx = await context_manager.get_or_create(chat_id)
    record = MessageRecord(
        message_id=message.message_id,
        user_id=user_id,
        username=username,
        text=message_text,
        has_image=pp.has_image,
        has_voice=pp.has_voice,
        media_description=pp.media_description,
    )
    await ctx.add_message(record)

    # --- Step 4: Build conversation context and run AI pipeline ----------------
    context_strings = await ctx.get_context_strings()
    # Exclude the current message from context
    conversation_context = context_strings[:-1] if len(context_strings) > 1 else []

    agent_input = AgentInput(
        message_text=message_text,
        user_id=user_id,
        group_id=chat_id,
        message_id=message.message_id,
        conversation_context=conversation_context,
        images=images,
    )

    logger.bind(**log_ctx).debug(
        "Processing message (images={}, has_voice={})",
        len(images),
        pp.has_voice,
    )
    output = await agent.process(agent_input)

    # --- Step 5: Sync to Zendesk via ZendeskSyncService -----------------------
    if sync_service:
        try:
            await sync_service.sync_message(
                group_id=chat_id,
                user_id=user_id,
                group_name=group_name,
                username=username,
                text=message_text,
                message_category=output.category.value,
                chat_id=chat_id,
                message_id=message.message_id,
                images=images or None,
                reply_to_message_id=reply_to_msg_id,
                conversation_context=conversation_context,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                tg_username=message.from_user.username,
            )
        except Exception as exc:  # noqa: BLE001
            logger.bind(**log_ctx).warning("Zendesk sync failed: {}", exc)

    # --- Step 6: Escalation (no reply) -----
    if output.needs_escalation:
        logger.bind(**log_ctx).info("Escalated — not replying in Telegram")
        return

    # --- Step 7: Reply if the agent decided to respond -------------------------
    if not output.should_reply:
        logger.bind(**log_ctx).debug("category={} — no reply", output.category.value)
        return

    raw_text = output.answer or output.follow_up_question or ""
    try:
        reply_text = format_reply(output)
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).error("Failed to format reply, falling back to raw text: {}", exc)
        reply_text = raw_text

    try:
        await message.reply(reply_text)
    except TelegramBadRequest as exc:
        if "can't parse entities" in str(exc):
            logger.bind(**log_ctx).warning(
                "MarkdownV2 parse failed, retrying as plain text: {}", exc
            )
            await message.reply(raw_text, parse_mode=None)
        else:
            raise

    # Sync bot response to Zendesk (answers and clarification follow-ups)
    if sync_service and raw_text:
        try:
            await sync_service.sync_bot_response(
                group_id=chat_id,
                user_id=user_id,
                text=raw_text,
            )
        except Exception as exc:  # noqa: BLE001
            logger.bind(**log_ctx).warning("Failed to sync bot response to Zendesk: {}", exc)

    # Record the bot reply in context
    bot_record = MessageRecord(
        message_id=0,
        user_id=0,
        username="Bot",
        text=raw_text[:200] if raw_text else "",
    )
    await ctx.add_message(bot_record)

    logger.bind(**log_ctx).info(
        "Replied category={} language={} escalated={}",
        output.category.value,
        output.language,
        output.needs_escalation,
    )
