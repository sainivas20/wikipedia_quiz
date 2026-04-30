"""
WikiQuiz - FastAPI Backend
Scrapes Wikipedia articles and generates quizzes using an LLM (Claude via Anthropic API).
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional
import httpx
import re
from bs4 import BeautifulSoup
from database import engine, Base, SessionLocal
import models
import crud
import llm_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create all tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="WikiQuiz API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request/Response Schemas ───────────────────────────────────────────────

class QuizRequest(BaseModel):
    url: str

class PreviewRequest(BaseModel):
    url: str


# ─── Helpers ────────────────────────────────────────────────────────────────

def is_valid_wikipedia_url(url: str) -> bool:
    """Validate that the URL is a Wikipedia article URL."""
    pattern = r"^https?://[a-z]{2,3}\.wikipedia\.org/wiki/.+"
    return bool(re.match(pattern, url))


async def scrape_wikipedia(url: str) -> dict:
    """
    Scrape a Wikipedia article using BeautifulSoup.
    Returns structured content: title, summary, sections, raw_html.
    """
    headers = {
        "User-Agent": "WikiQuizBot/1.0 (educational project; contact@example.com)"
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, headers=headers, follow_redirects=True)
        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to fetch Wikipedia page (HTTP {response.status_code})"
            )
        html = response.text

    soup = BeautifulSoup(html, "html.parser")

    # ── Title ──────────────────────────────────────────────────────────────
    title_tag = soup.find("h1", id="firstHeading")
    title = title_tag.get_text(strip=True) if title_tag else "Unknown Article"

    # ── Remove unwanted elements ───────────────────────────────────────────
    for tag in soup.select(
        "table, .navbox, .infobox, .mw-editsection, script, style, "
        ".reflist, .references, #toc, .toc, .noprint, sup.reference"
    ):
        tag.decompose()

    content_div = soup.find("div", id="mw-content-text")
    if not content_div:
        raise HTTPException(status_code=400, detail="Could not find article content.")

    # ── Summary (first 3 paragraphs) ───────────────────────────────────────
    paragraphs = content_div.find_all("p", recursive=True)
    meaningful = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 60]
    summary = " ".join(meaningful[:3])

    # ── Sections ───────────────────────────────────────────────────────────
    sections = []
    section_texts = {}
    for heading in content_div.find_all(["h2", "h3"]):
        section_name = heading.get_text(strip=True).replace("[edit]", "").strip()
        # Skip meta sections
        if section_name.lower() in ("references", "external links", "see also",
                                     "notes", "bibliography", "further reading"):
            continue
        # Collect text until next heading
        text_parts = []
        for sibling in heading.find_next_siblings():
            if sibling.name in ("h2", "h3"):
                break
            if sibling.name == "p":
                t = sibling.get_text(strip=True)
                if t:
                    text_parts.append(t)
        if text_parts:
            sections.append(section_name)
            section_texts[section_name] = " ".join(text_parts)

    # ── Full text for LLM (capped at ~6000 chars) ─────────────────────────
    full_text = summary
    for sec, txt in section_texts.items():
        full_text += f"\n\n== {sec} ==\n{txt}"
    full_text = full_text[:6000]

    return {
        "title": title,
        "summary": summary[:1000],
        "sections": sections[:10],
        "full_text": full_text,
        "raw_html": html[:50000],  # Store first 50k chars of raw HTML
    }


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "WikiQuiz API is running", "docs": "/docs"}


@app.post("/api/preview")
async def preview_article(req: PreviewRequest):
    """
    Quick endpoint: validate URL and fetch just the article title.
    Used by the frontend for URL preview before full processing.
    """
    if not is_valid_wikipedia_url(req.url):
        raise HTTPException(
            status_code=400,
            detail="Invalid URL. Please provide a valid Wikipedia article URL."
        )
    db = SessionLocal()
    try:
        existing = crud.get_quiz_by_url(db, req.url)
        if existing:
            return {
                "title": existing.title,
                "already_processed": True,
                "id": existing.id
            }
    finally:
        db.close()

    headers = {"User-Agent": "WikiQuizBot/1.0"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(req.url, headers=headers, follow_redirects=True)
            soup = BeautifulSoup(r.text, "html.parser")
            title_tag = soup.find("h1", id="firstHeading")
            title = title_tag.get_text(strip=True) if title_tag else req.url
            return {"title": title, "already_processed": False}
        except Exception:
            raise HTTPException(status_code=400, detail="Could not reach the URL.")


@app.post("/api/generate-quiz")
async def generate_quiz(req: QuizRequest):
    """
    Main endpoint: scrape Wikipedia URL and generate quiz via LLM.
    Caches results so the same URL is not processed twice.
    """
    url = req.url.strip()

    if not is_valid_wikipedia_url(url):
        raise HTTPException(
            status_code=400,
            detail="Invalid URL. Please provide a valid Wikipedia article URL "
                   "(e.g. https://en.wikipedia.org/wiki/Alan_Turing)."
        )

    db = SessionLocal()
    try:
        # ── Caching: return existing result if URL already processed ───────
        existing = crud.get_quiz_by_url(db, url)
        if existing:
            logger.info(f"Cache hit for URL: {url}")
            return crud.format_quiz_response(existing)

        # ── Scrape ─────────────────────────────────────────────────────────
        logger.info(f"Scraping: {url}")
        scraped = await scrape_wikipedia(url)

        # ── LLM generation ─────────────────────────────────────────────────
        logger.info("Sending to LLM...")
        llm_result = await llm_service.generate_quiz_content(
            title=scraped["title"],
            text=scraped["full_text"],
        )

        # ── Persist to DB ──────────────────────────────────────────────────
        record = crud.create_quiz_record(db, {
            "url": url,
            "title": scraped["title"],
            "summary": scraped["summary"],
            "sections": scraped["sections"],
            "raw_html": scraped["raw_html"],
            "key_entities": llm_result.get("key_entities", {}),
            "quiz": llm_result.get("quiz", []),
            "related_topics": llm_result.get("related_topics", []),
        })

        return crud.format_quiz_response(record)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
    finally:
        db.close()


@app.get("/api/history")
async def get_history():
    """Return all previously processed quizzes (summary list)."""
    db = SessionLocal()
    try:
        records = crud.get_all_quizzes(db)
        return [
            {
                "id": r.id,
                "url": r.url,
                "title": r.title,
                "summary": r.summary[:200] + "..." if r.summary and len(r.summary) > 200 else r.summary,
                "question_count": len(r.quiz) if r.quiz else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
    finally:
        db.close()


@app.get("/api/history/{quiz_id}")
async def get_quiz_detail(quiz_id: int):
    """Return full quiz detail by ID."""
    db = SessionLocal()
    try:
        record = crud.get_quiz_by_id(db, quiz_id)
        if not record:
            raise HTTPException(status_code=404, detail="Quiz not found.")
        return crud.format_quiz_response(record)
    finally:
        db.close()


@app.delete("/api/history/{quiz_id}")
async def delete_quiz(quiz_id: int):
    """Delete a quiz record by ID."""
    db = SessionLocal()
    try:
        success = crud.delete_quiz(db, quiz_id)
        if not success:
            raise HTTPException(status_code=404, detail="Quiz not found.")
        return {"message": "Deleted successfully."}
    finally:
        db.close()
