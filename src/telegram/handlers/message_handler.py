"""aiogram Router: handles incoming group and supergroup messages."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from loguru import logger

from src.agent.agent import SupportAgent
from src.agent.schemas import AgentInput
from src.telegram.context.context_manager import ContextManager
from src.telegram.context.group_context import MessageRecord
from src.telegram.formatter import format_reply

router = Router(name="group_messages")


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(
    message: Message,
    agent: SupportAgent,
    context_manager: ContextManager,
) -> None:
    """Process a single group message through the full agent pipeline.

    Args:
        message: Incoming aiogram Message object.
        agent: Injected :class:`SupportAgent` instance.
        context_manager: Injected :class:`ContextManager` singleton.
    """
    if not message.text or not message.from_user:
        return

    chat_id: int = message.chat.id
    user_id: int = message.from_user.id
    message_id: int = message.message_id
    username: str = message.from_user.full_name or str(user_id)

    log_ctx = {
        "group_id": chat_id,
        "user_id": user_id,
        "message_id": message_id,
    }

    # --- 1. Record the incoming message in the group context ----------------
    ctx = await context_manager.get_or_create(chat_id)
    record = MessageRecord(
        message_id=message_id,
        user_id=user_id,
        username=username,
        text=message.text,
    )
    await ctx.add_message(record)

    # --- 2. Build conversation context strings for the agent ----------------
    context_strings = await ctx.get_context_strings()
    # Exclude the current message from the context (it is already in agent_input.message_text)
    conversation_context = context_strings[:-1] if context_strings else []

    # --- 3. Build AgentInput and run the agent ------------------------------
    agent_input = AgentInput(
        message_text=message.text,
        user_id=user_id,
        group_id=chat_id,
        message_id=message_id,
        conversation_context=conversation_context,
    )

    logger.bind(**log_ctx).debug("Dispatching to SupportAgent")
    output = await agent.process(agent_input)

    # --- 4. Reply if the agent decided to respond ---------------------------
    if not output.should_reply:
        logger.bind(**log_ctx).debug("category={} — no reply", output.category.value)
        return

    reply_text = format_reply(output)

    await message.reply(reply_text)

    logger.bind(**log_ctx).info(
        "Replied category={} language={} escalated={}",
        output.category.value,
        output.language,
        output.needs_escalation,
    )
