"""
LLM Service — uses Google Gemini API (free tier) to generate quiz content.
Includes carefully crafted prompt templates for quiz generation and
related-topic suggestion, following LangChain-style template design.

Free-tier model used: gemini-1.5-flash
To switch to a paid model, change GEMINI_MODEL to "gemini-1.5-pro".
"""

import json
import os
import re
import httpx
import logging

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
# Set GEMINI_API_KEY in your .env / environment.
# Get your free API key at: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3-flash-preview"   # Free tier model (generous rate limits)
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


# ═══════════════════════════════════════════════════════════════════════════
# PROMPT TEMPLATES  (LangChain-style)
# ═══════════════════════════════════════════════════════════════════════════

QUIZ_GENERATION_SYSTEM_PROMPT = """\
You are an expert educational content creator specializing in generating \
high-quality, factual quiz questions from encyclopedic text.

Your quizzes are:
- Grounded exclusively in the provided article text (no hallucination)
- Varied in difficulty (mix of easy, medium, hard)
- Clear and unambiguous in wording
- Educational and thought-provoking

You always respond with valid JSON and nothing else."""

QUIZ_GENERATION_USER_TEMPLATE = """\
You are given the text of a Wikipedia article titled "{title}".

Article text (may be truncated):
---
{article_text}
---

Generate a JSON object with the following structure. Respond ONLY with \
the JSON object — no preamble, no markdown fences, no extra text.

{{
  "key_entities": {{
    "people": ["list of notable people mentioned"],
    "organizations": ["list of organizations mentioned"],
    "locations": ["list of locations mentioned"]
  }},
  "quiz": [
    {{
      "question": "Clear, specific question text",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "answer": "Exact text of the correct option",
      "difficulty": "easy | medium | hard",
      "explanation": "One sentence explaining why this answer is correct, \
citing where in the article this is mentioned."
    }}
  ],
  "related_topics": ["5-7 related Wikipedia article titles for further reading"]
}}

Rules:
1. Generate between 7 and 10 quiz questions.
2. Distribute difficulty: roughly 30% easy, 40% medium, 30% hard.
3. Every question must be answerable from the article text provided.
4. The "answer" field must exactly match one of the four "options".
5. Options should be plausible distractors — avoid obviously wrong choices.
6. Questions should cover different sections/aspects of the article.
7. related_topics should be real Wikipedia article titles (not URLs).
8. key_entities: include only entities explicitly mentioned in the article.
"""


# ═══════════════════════════════════════════════════════════════════════════
# LLM CALL  — Google Gemini free tier
# ═══════════════════════════════════════════════════════════════════════════

async def call_llm(system_prompt: str, user_prompt: str) -> str:
    """
    Call the Gemini API (free tier) and return the text response.

    Gemini free-tier limits (gemini-1.5-flash as of 2025):
      - 15 requests per minute
      - 1,000,000 tokens per minute
      - 1,500 requests per day

    To switch to a paid model, change GEMINI_MODEL to "gemini-1.5-pro".

    To switch back to Anthropic Claude, replace this function body with:
        headers = {
            "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=payload,
            )
            data = response.json()
            return data["content"][0]["text"]
    """
    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is not set. "
            "Get a free key at https://aistudio.google.com/app/apikey "
            "and set it in your .env file."
        )

    # Gemini combines system + user prompt via system_instruction + user turn
    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 4096,
            "temperature": 0.4,        # Lower = more factual/deterministic
            "responseMimeType": "application/json",  # Request JSON output
        },
    }

    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
        )

        if response.status_code == 429:
            raise RuntimeError(
                "Gemini free-tier rate limit hit (15 req/min or 1500 req/day). "
                "Please wait a moment and try again."
            )
        if response.status_code != 200:
            error_detail = response.text[:500]
            raise RuntimeError(
                f"Gemini API returned HTTP {response.status_code}: {error_detail}"
            )

        data = response.json()

        # Extract text from Gemini response structure
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("Gemini returned no candidates in response.")
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                raise RuntimeError("Gemini returned empty parts in response.")
            return parts[0].get("text", "")
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected Gemini response structure: {data}")
            raise RuntimeError(f"Failed to parse Gemini response: {e}") from e


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC INTERFACE
# ═══════════════════════════════════════════════════════════════════════════

async def generate_quiz_content(title: str, text: str) -> dict:
    """
    Main entry point. Fills in the prompt templates, calls the LLM,
    and returns a parsed dict with keys: key_entities, quiz, related_topics.
    """
    user_prompt = QUIZ_GENERATION_USER_TEMPLATE.format(
        title=title,
        article_text=text,
    )

    raw_response = await call_llm(QUIZ_GENERATION_SYSTEM_PROMPT, user_prompt)

    # ── Parse JSON safely ──────────────────────────────────────────────────
    # Strip accidental markdown fences if the model adds them
    cleaned = re.sub(r"```(?:json)?", "", raw_response).strip().rstrip("`").strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw response:\n{raw_response[:500]}")
        raise RuntimeError(
            "LLM returned malformed JSON. Please try again."
        ) from e

    # ── Validate and sanitize ──────────────────────────────────────────────
    quiz = result.get("quiz", [])
    validated_quiz = []
    for q in quiz:
        options = q.get("options", [])
        answer = q.get("answer", "")
        # Ensure answer is one of the options
        if answer not in options and options:
            answer = options[0]
        validated_quiz.append({
            "question": q.get("question", ""),
            "options": options[:4],  # cap at 4
            "answer": answer,
            "difficulty": q.get("difficulty", "medium"),
            "explanation": q.get("explanation", ""),
        })

    return {
        "key_entities": result.get("key_entities", {}),
        "quiz": validated_quiz,
        "related_topics": result.get("related_topics", []),
    }
