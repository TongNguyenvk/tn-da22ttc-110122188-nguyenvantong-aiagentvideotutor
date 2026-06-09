"""
AI Narrator - Generate narration text for each slide using Gemini.

Handles large decks with batching (Gotcha #3) and validates output
with exact slide count matching.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger("slide_narrator")

# Max slides per API call to avoid token overflow (Gotcha #3)
BATCH_SIZE = 20


async def generate_narrations(
    slides: list,
    task: str = "Create a lecture video explaining each slide",
    language: str = "Vietnamese",
    api_key: str = None,
) -> list[str]:
    """Generate narration text for each slide using AI.

    Handles large decks by batching (Gotcha #3).
    Validates that output count matches input slide count.

    Args:
        slides: List of SlideData objects
        task: User's description of the video purpose
        language: Target language for narrations
        api_key: Gemini API key (falls back to env var)

    Returns:
        List of narration strings, one per slide
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("No GEMINI_API_KEY, using slide text as narration fallback")
        return _fallback_narrations(slides)

    total = len(slides)
    if total == 0:
        return []

    # Batch processing for large decks (Gotcha #3)
    if total <= BATCH_SIZE:
        return await _generate_batch(slides, task, language, api_key, batch_offset=0)

    logger.info(f"Large deck ({total} slides), processing in batches of {BATCH_SIZE}")
    all_narrations = []
    for i in range(0, total, BATCH_SIZE):
        batch = slides[i:i + BATCH_SIZE]
        batch_narrations = await _generate_batch(
            batch, task, language, api_key, batch_offset=i
        )
        all_narrations.extend(batch_narrations)

    return all_narrations


async def _generate_batch(
    slides: list,
    task: str,
    language: str,
    api_key: str,
    batch_offset: int = 0,
) -> list[str]:
    """Generate narrations for a batch of slides."""
    from google import genai

    client = genai.Client(api_key=api_key)

    # Build slide content summary
    slides_content = []
    for slide in slides:
        slide_num = slide.slide_number
        text_content = " | ".join(slide.texts) if slide.texts else "(no text)"
        notes = slide.notes if slide.notes else "(no speaker notes)"
        slides_content.append(
            f"Slide {slide_num}:\n"
            f"  Content: {text_content}\n"
            f"  Speaker Notes: {notes}"
        )

    slides_text = "\n\n".join(slides_content)
    expected_count = len(slides)

    prompt = f"""You are a professional lecturer creating narration for a presentation video.

Task context: {task}

Here are the slides:

{slides_text}

Generate exactly {expected_count} narration scripts in {language}, one for each slide.
Each narration should:
- Be natural and conversational, as if a teacher is explaining to students
- Reference the content on the slide
- Use speaker notes as guidance if available
- Be 2-4 sentences long (suitable for 10-20 seconds of speech)
- Flow naturally from one slide to the next

IMPORTANT: You MUST return exactly {expected_count} narrations.

Return ONLY a valid JSON array of strings, no other text. Example:
["Narration for slide 1...", "Narration for slide 2...", ...]"""

    try:
        response = await client.aio.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
            contents=prompt,
        )
        text = response.text.strip()

        # Clean markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
        if text.startswith("json"):
            text = text[4:].strip()

        narrations = json.loads(text)

        # Validate count (Gotcha #3)
        if not isinstance(narrations, list):
            raise ValueError(f"Expected JSON array, got {type(narrations)}")

        if len(narrations) != expected_count:
            logger.warning(
                f"AI returned {len(narrations)} narrations, expected {expected_count}. "
                "Padding or trimming to match."
            )
            narrations = _fix_count(narrations, expected_count, slides)

        logger.info(f"Generated {len(narrations)} narrations (batch offset {batch_offset})")
        return narrations

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        logger.debug(f"Raw response: {text[:500]}")
        return _fallback_narrations(slides)

    except Exception as e:
        logger.error(f"AI narration failed: {e}")
        return _fallback_narrations(slides)


def _fix_count(narrations: list[str], expected: int, slides: list) -> list[str]:
    """Fix narration count to match slide count exactly (Gotcha #3)."""
    if len(narrations) > expected:
        return narrations[:expected]

    # Pad with fallback narrations
    while len(narrations) < expected:
        idx = len(narrations)
        if idx < len(slides):
            narrations.append(_slide_to_fallback(slides[idx]))
        else:
            narrations.append(f"Slide {idx + 1}.")
    return narrations


def _fallback_narrations(slides: list) -> list[str]:
    """Generate simple narrations from slide text when AI is unavailable."""
    return [_slide_to_fallback(s) for s in slides]


def _slide_to_fallback(slide) -> str:
    """Convert a single slide to a fallback narration."""
    if slide.notes:
        return slide.notes
    if slide.texts:
        return ". ".join(slide.texts[:3])
    return f"Slide {slide.slide_number}."
