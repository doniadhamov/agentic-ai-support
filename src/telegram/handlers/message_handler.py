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
from src.telegram.preprocessor import PreprocessedMessage, preprocess

router = Router(name="group_messages")

# Shared completeness checker (lazy-initialised on first use)
_checker: CompletenessChecker | None = None

# Maximum images to include in a single agent call
_MAX_IMAGES_PER_BATCH = 5


def _get_checker() -> CompletenessChecker:
    global _checker  # noqa: PLW0603
    if _checker is None:
        _checker = CompletenessChecker()
    return _checker


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


# ---------------------------------------------------------------------------
# Debounce buffer: accumulates messages per (group_id, user_id)
# ---------------------------------------------------------------------------


@dataclass
class _PendingBatch:
    """Holds buffered messages for a single (group, user) pair."""

    messages: list[Message] = field(default_factory=list)
    preprocessed: list[PreprocessedMessage] = field(default_factory=list)
    timer: asyncio.Task[None] | None = None
    first_message_time: float = field(default_factory=time.monotonic)


# key = (chat_id, user_id)
_pending: dict[tuple[int, int], _PendingBatch] = {}
_pending_lock = asyncio.Lock()


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
        texts = [pp.text for pp in batch.preprocessed]
        has_bare_photo = any(pp.has_image and not pp.text.strip() for pp in batch.preprocessed)
        has_voice = any(pp.has_voice for pp in batch.preprocessed)

        try:
            checker = _get_checker()
            complete = await checker.is_complete(
                texts,
                has_photo_without_text=has_bare_photo,
                has_voice=has_voice,
            )
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
    preprocessed_list = batch.preprocessed

    # Use the last message for replying (the most recent one)
    last_message = messages[-1]
    first_message = messages[0]
    username: str = first_message.from_user.full_name if first_message.from_user else str(user_id)

    log_ctx = {
        "group_id": chat_id,
        "user_id": user_id,
        "message_id": last_message.message_id,
        "batch_size": len(messages),
    }

    # --- Record all messages in group context --------------------------------
    ctx = await context_manager.get_or_create(chat_id)
    for msg, pp in zip(messages, preprocessed_list, strict=True):
        record = MessageRecord(
            message_id=msg.message_id,
            user_id=user_id,
            username=username,
            text=pp.text or msg.text or msg.caption or "",
            has_image=pp.has_image,
            has_voice=pp.has_voice,
            media_description=pp.media_description,
        )
        await ctx.add_message(record)

    # --- Combine preprocessed results into a single input --------------------
    texts: list[str] = []
    all_images: list[bytes] = []

    for pp in preprocessed_list:
        if pp.text:
            texts.append(pp.text)
        all_images.extend(pp.images)

    combined_text = "\n".join(texts)

    # Cap images to avoid excessive API costs
    if len(all_images) > _MAX_IMAGES_PER_BATCH:
        logger.bind(**log_ctx).warning(
            "Batch has {} images, capping to {}", len(all_images), _MAX_IMAGES_PER_BATCH
        )
        all_images = all_images[:_MAX_IMAGES_PER_BATCH]

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
        images=all_images,
    )

    logger.bind(**log_ctx).debug(
        "Dispatching batch of {} message(s) to SupportAgent (images={}, has_voice={})",
        len(messages),
        len(all_images),
        any(pp.has_voice for pp in preprocessed_list),
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
        logger.bind(**log_ctx).error("Failed to format reply, falling back to raw text: {}", exc)
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

    # Skip messages with no supported content (stickers, service messages, etc.)
    if not _has_supported_content(message):
        return

    chat_id: int = message.chat.id

    # --- Group allowlist guard ------------------------------------------------
    group_store = get_group_store()
    if group_store.has_groups() and not group_store.is_allowed(chat_id):
        return

    user_id: int = message.from_user.id
    log_ctx = {"group_id": chat_id, "user_id": user_id, "message_id": message.message_id}

    # --- Preprocess message (download media, transcribe voice, etc.) ----------
    pp = await preprocess(message, message.bot)
    if not pp.is_supported:
        logger.bind(**log_ctx).debug("Unsupported or failed preprocessing, skipping")
        return

    base_delay = get_settings().message_debounce_seconds

    # --- If debounce is disabled (0), process immediately ---------------------
    if base_delay <= 0:
        key = (chat_id, user_id)
        batch = _PendingBatch(messages=[message], preprocessed=[pp])
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
        batch.preprocessed.append(pp)

        # Cancel existing timer — the new _debounce_then_process task handles
        # both the silence wait and the semantic completeness loop.
        if batch.timer is not None and not batch.timer.done():
            batch.timer.cancel()

        batch.timer = asyncio.create_task(_debounce_then_process(key, agent, context_manager))

    logger.bind(**log_ctx).debug(
        "Buffered message (batch size now {}), debounce in {:.1f}s",
        len(batch.messages),
        base_delay,
    )
