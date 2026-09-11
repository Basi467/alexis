import json
import logging
import time
from typing import Any

import groq
from groq import Groq

from config import GROQ_API_KEY

logger = logging.getLogger(__name__)

try:
    client: Groq | None = Groq(api_key=GROQ_API_KEY, timeout=15.0)
except Exception:
    logger.exception("Failed to initialize Groq client")
    client = None

MODEL = "openai/gpt-oss-120b"
# The main MODEL above is text-only. This is the only model on the account
# that accepts image input, confirmed against the live /v1/models list.
VISION_MODEL = "qwen/qwen3.8-27b"
# Same model family as MODEL, much smaller -- used for cheap classification-style
# calls (yes/no, pick-a-number, structured field extraction) that don't need full
# conversational quality. Cuts latency and reduces how fast the account's rate
# limit gets used up, since these calls happen multiple times per turn.
CLASSIFICATION_MODEL = "openai/gpt-oss-20b"

RATE_LIMIT_MESSAGE = "I've hit my usage limit for now and need to wait a bit before I can respond."
GENERIC_FAILURE_MESSAGE = "I'm having trouble reaching my brain right now. Please try again in a moment."


def chat_completion(
    messages: list[dict],
    tools: list[dict] | None = None,
    retries: int = 2,
    model: str = MODEL,
) -> tuple[Any | None, str | None]:
    """Lower-level than ask_groq: returns the raw SDK message object (so callers
    can see every tool_call and its id, needed to properly continue a multi-step
    tool-calling conversation) instead of just the first tool call's parsed args.

    Returns (message, None) on success, or (None, user_facing_error_text) on
    failure -- callers don't need to know or handle the different Groq exception
    types themselves, just check which element is None.
    """
    if client is None:
        return None, "I'm having trouble connecting to my brain right now."

    current_tools = tools
    for attempt in range(retries):
        try:
            kwargs: dict[str, Any] = {"model": model, "messages": messages}
            if current_tools:
                kwargs["tools"] = current_tools

            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message, None

        except groq.BadRequestError as e:
            logger.warning("Groq API attempt %d failed with bad request: %s", attempt + 1, e)
            if current_tools and "tool_use_failed" in str(e):
                logger.info("Retrying without tools due to malformed tool call.")
                current_tools = None
                continue
            break

        except groq.RateLimitError as e:
            # Retrying won't help here — Groq's rate limits (especially the daily token
            # cap on the free tier) need minutes, not the 1s backoff below, to clear.
            # Retrying anyway just wastes a round trip and still fails, so fail fast
            # with an honest message instead of the generic "having trouble" one.
            logger.warning("Groq rate limit hit: %s", e)
            return None, RATE_LIMIT_MESSAGE

        except groq.GroqError as e:
            logger.warning("Groq API attempt %d failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(1)

    return None, GENERIC_FAILURE_MESSAGE


def ask_groq(
    user_text: str,
    conversation_history: list[dict] | None = None,
    retries: int = 2,
    tools: list[dict] | None = None,
    model: str = MODEL,
) -> tuple[str, dict[str, Any] | None]:
    """Simple one-shot wrapper: (text, first_tool_call_or_None). Used everywhere
    that doesn't need multi-step tool chaining -- memory/rule update classification,
    confirmation yes/no classification, styled alarm/reminder messages, the
    greeting. For chaining multiple tool calls in one turn, see llm/router.py's
    agent loop, which uses chat_completion() directly."""
    if conversation_history is None:
        conversation_history = []
    messages = conversation_history + [{"role": "user", "content": user_text}]

    message, error = chat_completion(messages, tools=tools, retries=retries, model=model)
    if message is None:
        return error, None

    tool_call_result = None
    if message.tool_calls:
        call = message.tool_calls[0]
        args = json.loads(call.function.arguments)
        tool_call_result = {"name": call.function.name, "arguments": args}

    return message.content or "", tool_call_result


def ask_vision(question: str, image_base64: str, retries: int = 2) -> tuple[str, str | None]:
    """Single image + question, using VISION_MODEL since the main agent-loop MODEL
    can't see images. Returns (answer, None) on success, or (error_text, error_text)
    on failure -- always check the second element, the first is user-facing either way."""
    if client is None:
        message = "I'm having trouble connecting to my brain right now."
        return message, message

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
        ],
    }]

    for attempt in range(retries):
        try:
            # max_tokens matters here beyond just cost: confirmed live, this call
            # with no cap freely ran to 1200-1700+ output tokens regardless of how
            # the question was phrased (a "be concise" instruction in the prompt
            # wasn't reliably obeyed), which alone exceeded Groq's 1000 output-
            # tokens-per-minute limit for this model and made every other call
            # fail with a 429. A hard cap fixes the rate limit and, as a side
            # effect, forces a shorter answer with less room to fabricate detail.
            response = client.chat.completions.create(
                model=VISION_MODEL, messages=messages, max_tokens=500,
            )
            return response.choices[0].message.content or "", None

        except groq.RateLimitError as e:
            logger.warning("Groq vision rate limit hit: %s", e)
            return RATE_LIMIT_MESSAGE, RATE_LIMIT_MESSAGE

        except groq.GroqError as e:
            logger.warning("Groq vision attempt %d failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(1)

    return GENERIC_FAILURE_MESSAGE, GENERIC_FAILURE_MESSAGE
