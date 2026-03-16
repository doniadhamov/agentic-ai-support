"""aiogram Router: handles incoming group and supergroup messages.

Implements a smart per-user debounce: consecutive messages from the same user
in the same group are batched into a single agent call.  After the base silence
timer fires, a fast semantic check (Haiku) decides whether the batch looks
complete or the user is still typing — extending the wait up to a configurable
maximum.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from loguru import logger

from src.admin.group_store import get_group_store
from src.agent.agent import SupportAgent
from src.agent.completeness_checker import CompletenessChecker
from src.agent.schemas import AgentInput
from src.config.settings import get_settings
from src.telegram.context.context_manager import ContextManager
from src.telegram.context.group_context import MessageRecord
from src.telegram.formatter import format_reply

router = Router(name="group_messages")

# Maximum photo file size we're willing to download (5 MB)
_MAX_PHOTO_BYTES = 5 * 1024 * 1024

# Shared completeness checker (lazy-initialised on first use)
_checker: CompletenessChecker | None = None


def _get_checker() -> CompletenessChecker:
    global _checker  # noqa: PLW0603
    if _checker is None:
        _checker = CompletenessChecker()
    return _checker


# ---------------------------------------------------------------------------
# Debounce buffer: accumulates messages per (group_id, user_id)
# ---------------------------------------------------------------------------


@dataclass
class _PendingBatch:
    """Holds buffered messages for a single (group, user) pair."""

    messages: list[Message] = field(default_factory=list)
    image_data_list: list[bytes | None] = field(default_factory=list)
    timer: asyncio.Task[None] | None = None
    first_message_time: float = field(default_factory=time.monotonic)


# key = (chat_id, user_id)
_pending: dict[tuple[int, int], _PendingBatch] = {}
_pending_lock = asyncio.Lock()


async def _download_photo(message: Message, log_ctx: dict) -> bytes | None:
    """Download the largest photo from a message, if present."""
    if not message.photo:
        return None
    try:
        photo = message.photo[-1]
        if photo.file_size and photo.file_size > _MAX_PHOTO_BYTES:
            logger.bind(**log_ctx).warning(
                "Photo too large ({} bytes), skipping image", photo.file_size
            )
            return None
        from io import BytesIO

        buf = BytesIO()
        await message.bot.download(photo, destination=buf)
        data = buf.getvalue()
        logger.bind(**log_ctx).debug("Downloaded photo ({} bytes)", len(data))
        return data
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).warning("Failed to download photo: {}", exc)
        return None


async def _debounce_then_process(
    key: tuple[int, int],
    agent: SupportAgent,
    context_manager: ContextManager,
) -> None:
    """Wait for the base debounce period, then semantically check completeness.

    If the batch looks incomplete and the max wait budget allows, wait another
    base period and re-check.  Repeats until the batch is complete or the
    budget is exhausted.
    """
    settings = get_settings()
    base_delay = settings.message_debounce_seconds
    max_total = settings.message_debounce_max_seconds

    # --- Phase 1: initial silence wait --------------------------------------
    await asyncio.sleep(base_delay)

    # --- Phase 2: semantic completeness loop --------------------------------
    while True:
        async with _pending_lock:
            batch = _pending.get(key)
        if not batch or not batch.messages:
            return

        elapsed = time.monotonic() - batch.first_message_time
        remaining_budget = max_total - elapsed

        # Budget exhausted — process regardless
        if remaining_budget <= base_delay:
            break

        # Collect texts for the completeness check
        texts = [m.text or m.caption or "" for m in batch.messages]
        has_bare_photo = any(
            bool(m.photo) and not (m.text or m.caption or "").strip()
            for m in batch.messages
        )

        try:
            checker = _get_checker()
            complete = await checker.is_complete(texts, has_photo_without_text=has_bare_photo)
        except Exception:  # noqa: BLE001
            logger.debug("Completeness check failed, treating as complete")
            break

        if complete:
            break

        # Incomplete — wait another base period for more messages
        logger.debug(
            "Batch for {} looks incomplete ({} msgs, {:.1f}s elapsed), waiting {:.1f}s more",
            key,
            len(batch.messages),
            elapsed,
            base_delay,
        )
        await asyncio.sleep(base_delay)

    # --- Process the final batch --------------------------------------------
    await _process_batch(key, agent, context_manager)


async def _process_batch(
    key: tuple[int, int],
    agent: SupportAgent,
    context_manager: ContextManager,
) -> None:
    """Process all buffered messages for *key* as a single agent call."""
    async with _pending_lock:
        batch = _pending.pop(key, None)
    if not batch or not batch.messages:
        return

    chat_id, user_id = key
    messages = batch.messages
    image_data_list = batch.image_data_list

    # Use the last message for replying (the most recent one)
    last_message = messages[-1]
    first_message = messages[0]
    username: str = (
        first_message.from_user.full_name if first_message.from_user else str(user_id)
    )

    log_ctx = {
        "group_id": chat_id,
        "user_id": user_id,
        "message_id": last_message.message_id,
        "batch_size": len(messages),
    }

    # --- Record all messages in group context --------------------------------
    ctx = await context_manager.get_or_create(chat_id)
    for msg, _img in zip(messages, image_data_list, strict=True):
        msg_text = msg.text or msg.caption or ""
        record = MessageRecord(
            message_id=msg.message_id,
            user_id=user_id,
            username=username,
            text=msg_text,
            has_image=bool(msg.photo),
        )
        await ctx.add_message(record)

    # --- Combine message texts into a single input ---------------------------
    texts: list[str] = []
    for msg in messages:
        t = msg.text or msg.caption or ""
        if t:
            texts.append(t)
    combined_text = "\n".join(texts)

    # Pick the last available image (most relevant / most recent)
    image_data: bytes | None = None
    for img in reversed(image_data_list):
        if img:
            image_data = img
            break

    has_any_photo = any(bool(msg.photo) for msg in messages)

    # --- Build conversation context strings for the agent --------------------
    context_strings = await ctx.get_context_strings()
    # Exclude the current batch messages from context (already in combined_text)
    batch_count = len(messages)
    conversation_context = (
        context_strings[:-batch_count] if len(context_strings) >= batch_count else []
    )

    # --- Build AgentInput and run the agent ----------------------------------
    agent_input = AgentInput(
        message_text=combined_text,
        user_id=user_id,
        group_id=chat_id,
        message_id=last_message.message_id,
        conversation_context=conversation_context,
        image_data=image_data,
    )

    logger.bind(**log_ctx).debug(
        "Dispatching batch of {} message(s) to SupportAgent (has_image={})",
        len(messages),
        has_any_photo,
    )
    output = await agent.process(agent_input)

    # --- Reply if the agent decided to respond -------------------------------
    if not output.should_reply:
        logger.bind(**log_ctx).debug("category={} — no reply", output.category.value)
        return

    # --- Format the reply text (MarkdownV2 conversion) ----------------------
    raw_text = output.answer or output.follow_up_question or ""
    try:
        reply_text = format_reply(output)
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).error(
            "Failed to format reply, falling back to raw text: {}", exc
        )
        reply_text = raw_text

    # --- Send the reply to the last message in the batch --------------------
    try:
        await last_message.reply(reply_text)
    except TelegramBadRequest as exc:
        if "can't parse entities" in str(exc):
            logger.bind(**log_ctx).warning(
                "MarkdownV2 parse failed, retrying as plain text: {}", exc
            )
            await last_message.reply(raw_text, parse_mode=None)
        else:
            raise

    # --- Record the bot reply in context ------------------------------------
    bot_record = MessageRecord(
        message_id=0,
        user_id=0,
        username="Bot",
        text=raw_text[:200] if raw_text else "",
    )
    await ctx.add_message(bot_record)

    logger.bind(**log_ctx).info(
        "Replied category={} language={} escalated={} batch_size={}",
        output.category.value,
        output.language,
        output.needs_escalation,
        len(messages),
    )


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(
    message: Message,
    agent: SupportAgent,
    context_manager: ContextManager,
) -> None:
    """Buffer incoming group messages and process them after a smart debounce.

    When a user sends multiple messages in quick succession, all messages are
    combined into a single agent call.  After the base silence timer, a fast
    Haiku call checks whether the batch looks semantically complete — if not,
    the wait is extended up to ``MESSAGE_DEBOUNCE_MAX_SECONDS``.
    """
    if not message.from_user:
        return

    message_text: str = message.text or message.caption or ""
    has_photo: bool = bool(message.photo)

    if not message_text and not has_photo:
        return

    chat_id: int = message.chat.id

    # --- Group allowlist guard ------------------------------------------------
    group_store = get_group_store()
    if group_store.has_groups() and not group_store.is_allowed(chat_id):
        return

    user_id: int = message.from_user.id
    log_ctx = {"group_id": chat_id, "user_id": user_id, "message_id": message.message_id}

    # --- Download photo bytes if present --------------------------------------
    image_data = await _download_photo(message, log_ctx)

    base_delay = get_settings().message_debounce_seconds

    # --- If debounce is disabled (0), process immediately ---------------------
    if base_delay <= 0:
        key = (chat_id, user_id)
        batch = _PendingBatch(messages=[message], image_data_list=[image_data])
        async with _pending_lock:
            _pending[key] = batch
        await _process_batch(key, agent, context_manager)
        return

    # --- Buffer the message and (re)start the debounce timer -----------------
    key = (chat_id, user_id)

    async with _pending_lock:
        batch = _pending.get(key)
        if batch is None:
            batch = _PendingBatch()
            _pending[key] = batch

        batch.messages.append(message)
        batch.image_data_list.append(image_data)

        # Cancel existing timer — the new _debounce_then_process task handles
        # both the silence wait and the semantic completeness loop.
        if batch.timer is not None and not batch.timer.done():
            batch.timer.cancel()

        batch.timer = asyncio.create_task(
            _debounce_then_process(key, agent, context_manager)
        )

    logger.bind(**log_ctx).debug(
        "Buffered message (batch size now {}), debounce in {:.1f}s",
        len(batch.messages),
        base_delay,
    )
