from collections.abc import Callable
from typing import Any

from loguru import logger
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def async_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 10.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[..., Any]:
    """Decorator: retry an async function with exponential back-off."""
    import functools

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
                retry=retry_if_exception_type(exceptions),
                reraise=True,
            ):
                with attempt:
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        logger.warning(
                            f"Retrying {func.__name__} "
                            f"(attempt {attempt.retry_state.attempt_number}/{max_attempts}): {e}"
                        )
                        raise

        return wrapper

    return decorator
