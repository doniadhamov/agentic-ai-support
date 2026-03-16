"""aiogram Router: handles incoming group and supergroup messages."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from loguru import logger

from src.admin.group_store import get_group_store
from src.agent.agent import SupportAgent
from src.agent.schemas import AgentInput
from src.telegram.context.context_manager import ContextManager
from src.telegram.context.group_context import MessageRecord
from src.telegram.formatter import format_reply

router = Router(name="group_messages")

# Maximum photo file size we're willing to download (5 MB)
_MAX_PHOTO_BYTES = 5 * 1024 * 1024


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(
    message: Message,
    agent: SupportAgent,
    context_manager: ContextManager,
) -> None:
    """Process a single group message through the full agent pipeline.

    Handles both text-only messages and photo messages (with or without captions).

    Args:
        message: Incoming aiogram Message object.
        agent: Injected :class:`SupportAgent` instance.
        context_manager: Injected :class:`ContextManager` singleton.
    """
    if not message.from_user:
        return

    # Determine text content: regular text or photo caption
    message_text: str = message.text or message.caption or ""
    has_photo: bool = bool(message.photo)

    # Skip messages with no text AND no photo
    if not message_text and not has_photo:
        return

    chat_id: int = message.chat.id

    # --- Group allowlist guard ------------------------------------------------
    group_store = get_group_store()
    if group_store.has_groups() and not group_store.is_allowed(chat_id):
        return
    user_id: int = message.from_user.id
    message_id: int = message.message_id
    username: str = message.from_user.full_name or str(user_id)

    log_ctx = {
        "group_id": chat_id,
        "user_id": user_id,
        "message_id": message_id,
    }

    # --- Download photo bytes if present --------------------------------------
    image_data: bytes | None = None
    if has_photo:
        try:
            # message.photo is sorted by size; pick the largest available
            photo = message.photo[-1]
            if photo.file_size and photo.file_size > _MAX_PHOTO_BYTES:
                logger.bind(**log_ctx).warning(
                    "Photo too large ({} bytes), skipping image", photo.file_size
                )
            else:
                from io import BytesIO

                buf = BytesIO()
                await message.bot.download(photo, destination=buf)
                image_data = buf.getvalue()
                logger.bind(**log_ctx).debug("Downloaded photo ({} bytes)", len(image_data))
        except Exception as exc:  # noqa: BLE001
            logger.bind(**log_ctx).warning("Failed to download photo: {}", exc)

    # --- 1. Record the incoming message in the group context ----------------
    ctx = await context_manager.get_or_create(chat_id)
    record = MessageRecord(
        message_id=message_id,
        user_id=user_id,
        username=username,
        text=message_text,
        has_image=has_photo,
    )
    await ctx.add_message(record)

    # --- 2. Build conversation context strings for the agent ----------------
    context_strings = await ctx.get_context_strings()
    # Exclude the current message from the context (it is already in agent_input.message_text)
    conversation_context = context_strings[:-1] if context_strings else []

    # --- 3. Build AgentInput and run the agent ------------------------------
    agent_input = AgentInput(
        message_text=message_text,
        user_id=user_id,
        group_id=chat_id,
        message_id=message_id,
        conversation_context=conversation_context,
        image_data=image_data,
    )

    logger.bind(**log_ctx).debug("Dispatching to SupportAgent (has_image={})", has_photo)
    output = await agent.process(agent_input)

    # --- 4. Reply if the agent decided to respond ---------------------------
    if not output.should_reply:
        logger.bind(**log_ctx).debug("category={} — no reply", output.category.value)
        return

    # --- Format the reply text (MarkdownV2 conversion) ----------------------
    raw_text = output.answer or output.follow_up_question or ""
    try:
        reply_text = format_reply(output)
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).error("Failed to format reply, falling back to raw text: {}", exc)
        reply_text = raw_text

    # --- Send the reply, with fallback to plain text -----------------------
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

    # --- Record the bot reply in context so the classifier sees the full conversation ---
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
