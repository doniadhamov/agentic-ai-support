"""Message preprocessor: normalizes any supported Telegram message type into text + images.

Supported types:
- Text messages
- Photos (with/without caption)
- Voice / audio messages (transcribed via Gemini Flash)
- Documents with image/* MIME type (treated as photos)

All other message types produce an empty PreprocessedMessage and are skipped.
"""

from __future__ import annotations

from io import BytesIO

from aiogram import Bot
from aiogram.types import Message
from google import genai
from google.genai import types
from loguru import logger
from pydantic import BaseModel, Field

from src.config.settings import get_settings
from src.utils.retry import async_retry

# Maximum photo/image file size (5 MB)
_MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Maximum voice/audio file size (10 MB)
_MAX_VOICE_BYTES = 10 * 1024 * 1024


class PreprocessedMessage(BaseModel):
    """Normalized representation of any Telegram message type."""

    text: str = Field(default="", description="Text content or transcription")
    images: list[bytes] = Field(
        default_factory=list,
        description="Zero or more image byte arrays",
        exclude=True,
    )
    media_description: str = Field(
        default="",
        description="Human-readable description for context window",
    )
    has_voice: bool = Field(default=False, description="Whether the message was a voice/audio")
    has_image: bool = Field(default=False, description="Whether the message had images")
    is_supported: bool = Field(
        default=False,
        description="Whether the message type is supported for processing",
    )


async def preprocess(message: Message, bot: Bot) -> PreprocessedMessage:
    """Preprocess a Telegram message into a normalized format.

    Routes to the appropriate handler based on message content type.
    Returns an empty PreprocessedMessage for unsupported types.
    """
    log_ctx = {
        "chat_id": message.chat.id,
        "message_id": message.message_id,
    }

    # Voice / audio messages
    if message.voice or message.audio:
        return await _handle_voice(message, bot, log_ctx)

    # Photo messages
    if message.photo:
        return await _handle_photo(message, bot, log_ctx)

    # Document with image MIME type
    if (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("image/")
    ):
        return await _handle_image_document(message, bot, log_ctx)

    # Plain text messages
    if message.text:
        return PreprocessedMessage(
            text=message.text,
            is_supported=True,
        )

    # Caption-only (rare, but possible)
    if message.caption:
        return PreprocessedMessage(
            text=message.caption,
            is_supported=True,
        )

    # Unsupported message type
    logger.bind(**log_ctx).debug("Unsupported message type, skipping")
    return PreprocessedMessage()


async def _handle_photo(message: Message, bot: Bot, log_ctx: dict) -> PreprocessedMessage:
    """Download photo and extract caption."""
    caption = message.caption or ""
    image_bytes = await _download_photo(message, bot, log_ctx)

    if image_bytes:
        return PreprocessedMessage(
            text=caption,
            images=[image_bytes],
            has_image=True,
            is_supported=True,
        )

    # Photo download failed — fall back to caption-only if available
    if caption:
        return PreprocessedMessage(text=caption, is_supported=True)
    return PreprocessedMessage()


async def _handle_voice(message: Message, bot: Bot, log_ctx: dict) -> PreprocessedMessage:
    """Download voice/audio message and transcribe via Gemini Flash."""
    settings = get_settings()

    # Check duration limit
    voice = message.voice or message.audio
    if not voice:
        return PreprocessedMessage()

    duration = voice.duration or 0
    if duration > settings.max_voice_duration_seconds:
        logger.bind(**log_ctx).warning(
            "Voice message too long ({} seconds, max {}), skipping",
            duration,
            settings.max_voice_duration_seconds,
        )
        return PreprocessedMessage(
            media_description="[voice message — too long to process]",
            has_voice=True,
            is_supported=False,
        )

    # Check file size
    file_size = voice.file_size or 0
    if file_size > _MAX_VOICE_BYTES:
        logger.bind(**log_ctx).warning("Voice file too large ({} bytes), skipping", file_size)
        return PreprocessedMessage(
            media_description="[voice message — file too large]",
            has_voice=True,
            is_supported=False,
        )

    # Download voice file
    try:
        buf = BytesIO()
        await bot.download(voice, destination=buf)
        audio_bytes = buf.getvalue()
        logger.bind(**log_ctx).debug("Downloaded voice message ({} bytes)", len(audio_bytes))
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).warning("Failed to download voice message: {}", exc)
        return PreprocessedMessage(
            media_description="[voice message — download failed]",
            has_voice=True,
            is_supported=False,
        )

    # Determine MIME type
    mime_type = "audio/ogg"
    if message.audio and message.audio.mime_type:
        mime_type = message.audio.mime_type

    # Transcribe
    transcription = await _transcribe_audio(audio_bytes, mime_type, log_ctx)
    if not transcription:
        return PreprocessedMessage(
            media_description="[voice message — transcription failed]",
            has_voice=True,
            is_supported=False,
        )

    logger.bind(**log_ctx).info("Voice transcription: {} chars", len(transcription))

    return PreprocessedMessage(
        text=transcription,
        media_description="[voice message]",
        has_voice=True,
        is_supported=True,
    )


async def _handle_image_document(message: Message, bot: Bot, log_ctx: dict) -> PreprocessedMessage:
    """Download a document with image/* MIME type and treat it as a photo."""
    doc = message.document
    if not doc:
        return PreprocessedMessage()

    file_size = doc.file_size or 0
    if file_size > _MAX_IMAGE_BYTES:
        logger.bind(**log_ctx).warning("Image document too large ({} bytes), skipping", file_size)
        return PreprocessedMessage()

    try:
        buf = BytesIO()
        await bot.download(doc, destination=buf)
        image_bytes = buf.getvalue()
        logger.bind(**log_ctx).debug(
            "Downloaded image document ({} bytes, {})", len(image_bytes), doc.mime_type
        )
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).warning("Failed to download image document: {}", exc)
        return PreprocessedMessage()

    caption = message.caption or ""
    return PreprocessedMessage(
        text=caption,
        images=[image_bytes],
        has_image=True,
        is_supported=True,
    )


async def _download_photo(message: Message, bot: Bot, log_ctx: dict) -> bytes | None:
    """Download the largest photo from a message."""
    if not message.photo:
        return None

    photo = message.photo[-1]  # Largest size
    if photo.file_size and photo.file_size > _MAX_IMAGE_BYTES:
        logger.bind(**log_ctx).warning("Photo too large ({} bytes), skipping", photo.file_size)
        return None

    try:
        buf = BytesIO()
        await bot.download(photo, destination=buf)
        data = buf.getvalue()
        logger.bind(**log_ctx).debug("Downloaded photo ({} bytes)", len(data))
        return data
    except Exception as exc:  # noqa: BLE001
        logger.bind(**log_ctx).warning("Failed to download photo: {}", exc)
        return None


@async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0)
async def _transcribe_audio(audio_bytes: bytes, mime_type: str, log_ctx: dict) -> str:
    """Transcribe audio bytes using Gemini Flash.

    Args:
        audio_bytes: Raw audio file bytes (OGG, MP3, etc.).
        mime_type: Audio MIME type.
        log_ctx: Logging context dict.

    Returns:
        Transcription text, or empty string on failure.
    """
    settings = get_settings()
    client = genai.Client(api_key=settings.google_api_key)

    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)

    logger.bind(**log_ctx).debug(
        "Transcribing audio ({} bytes, {}) with {}",
        len(audio_bytes),
        mime_type,
        settings.gemini_flash_model,
    )

    response = await client.aio.models.generate_content(
        model=settings.gemini_flash_model,
        contents=[
            audio_part,
            "Transcribe the following audio message exactly. "
            "Return only the transcription text, nothing else. "
            "If the audio is in a non-English language, transcribe in the original language.",
        ],
    )

    if response.text:
        return response.text.strip()
    return ""
