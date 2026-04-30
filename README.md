# WikiQuiz — AI-Powered Wikipedia Quiz Generator

Generate intelligent, multi-difficulty quizzes from any Wikipedia article using Google Gemini (free tier). Built with FastAPI, SQLAlchemy, BeautifulSoup, and a vanilla HTML/JS frontend.

> **LLM Provider:** This version uses **Google Gemini `gemini-1.5-flash`** — completely free, no credit card required.  
> Get your free API key at: https://aistudio.google.com/app/apikey

---

## Architecture Overview

```
wikiquiz/
├── main.py              # FastAPI app, routes, Wikipedia scraping logic
├── database.py          # SQLAlchemy engine setup (PostgreSQL / SQLite)
├── models.py            # ORM model: QuizRecord
├── crud.py              # Database CRUD helpers
├── llm_service.py       # Gemini prompt templates + API call (FREE TIER)
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── index.html           # Single-file SPA frontend (vanilla JS, no build step)
├── example_urls.txt     # Sample Wikipedia URLs to test with
├── alan_turing_output.json  # Sample output for reference
└── README.md
```

---

## Quick Start

### 1. Get a Free Gemini API Key

1. Go to https://aistudio.google.com/app/apikey
2. Sign in with your Google account
3. Click **"Create API key"**
4. Copy the key (starts with `AIza...`)

**Free tier limits for `gemini-1.5-flash`:**
- 15 requests per minute
- 1,000,000 tokens per minute
- 1,500 requests per day

No credit card, no billing setup required.

---

### 2. Backend Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file:

```bash
cp .env.example .env
# Then edit .env and paste your Gemini API key
```

Your `.env` should look like:

```env
GEMINI_API_KEY=AIzaSyABZjk1_jb92YFbAZZkC0-atRFuCNp9sbY

# Optional: PostgreSQL (defaults to SQLite if not set)
# DATABASE_URL=postgresql://user:password@localhost:5432/wikiquiz
```

Start the server:

```bash
uvicorn main:app --reload --port 8000
```

API available at: `http://localhost:8000`  
Swagger docs: `http://localhost:8000/docs`

---

### 3. Frontend Setup

No build step needed — it's a single HTML file.

```bash
# Option A: open directly in browser
open index.html

# Option B: serve with Python's built-in server
python -m http.server 3000
# then visit http://localhost:3000
```

> **CORS:** The backend allows all origins by default. For production, restrict `allow_origins` in `main.py`.

---

### 4. Database (Optional — PostgreSQL)

By default, WikiQuiz uses **SQLite** automatically (no setup needed, stored in `wikiquiz.db`).

To use PostgreSQL instead:

```sql
CREATE DATABASE wikiquiz;
CREATE USER wikiquizuser WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE wikiquiz TO wikiquizuser;
```

Then set in `.env`:
```env
DATABASE_URL=postgresql://wikiquizuser:yourpassword@localhost:5432/wikiquiz
```

Tables are auto-created on first startup.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/preview` | Fetch article title for a URL (pre-validation) |
| `POST` | `/api/generate-quiz` | Scrape + generate quiz (with caching) |
| `GET` | `/api/history` | List all previously generated quizzes |
| `GET` | `/api/history/{id}` | Get full quiz detail by ID |
| `DELETE` | `/api/history/{id}` | Delete a quiz record |

### POST `/api/generate-quiz`

**Request:**
```json
{ "url": "https://en.wikipedia.org/wiki/Alan_Turing" }
```

**Response:**
```json
{
  "id": 1,
  "url": "https://en.wikipedia.org/wiki/Alan_Turing",
  "title": "Alan Turing",
  "summary": "...",
  "key_entities": {
    "people": ["Alan Turing", "..."],
    "organizations": ["Bletchley Park", "..."],
    "locations": ["Cambridge", "..."]
  },
  "quiz": [
    {
      "question": "Where did Alan Turing study?",
      "options": ["Harvard University", "King's College, Cambridge", "Oxford University", "Princeton University"],
      "answer": "King's College, Cambridge",
      "difficulty": "easy",
      "explanation": "Mentioned in the 'Early life' section."
    }
  ],
  "related_topics": ["Enigma machine", "Bletchley Park", "..."]
}
```

---

## How the Gemini Integration Works

The entire LLM logic lives in `llm_service.py`. Key details:

- **Model:** `gemini-1.5-flash` — fastest free-tier model, great for structured JSON output
- **No extra SDK needed** — calls the Gemini REST API directly using `httpx` (already in requirements)
- **System instruction** — Gemini supports a dedicated `system_instruction` field (equivalent to Claude's `system` parameter)
- **JSON mode** — `responseMimeType: "application/json"` is set so Gemini returns clean JSON without markdown fences
- **Rate limit handling** — HTTP 429 responses return a friendly message explaining the free-tier limit

### Gemini API request structure

```python
payload = {
    "system_instruction": {
        "parts": [{"text": system_prompt}]
    },
    "contents": [
        {"role": "user", "parts": [{"text": user_prompt}]}
    ],
    "generationConfig": {
        "maxOutputTokens": 4096,
        "temperature": 0.4,
        "responseMimeType": "application/json",
    },
}
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
```

---

## LLM Prompt Templates

Both templates are in `llm_service.py`.

### System Prompt
```
You are an expert educational content creator specializing in generating
high-quality, factual quiz questions from encyclopedic text.
You always respond with valid JSON and nothing else.
```

### User Prompt Template
```
You are given the text of a Wikipedia article titled "{title}".

Article text (may be truncated):
---
{article_text}
---

Generate a JSON object with the following structure...

Rules:
1. Generate between 7 and 10 quiz questions.
2. Distribute difficulty: roughly 30% easy, 40% medium, 30% hard.
3. Every question must be answerable from the article text provided.
4. The "answer" field must exactly match one of the four "options".
5. Options should be plausible distractors — avoid obviously wrong choices.
6. Questions should cover different sections/aspects of the article.
7. related_topics should be real Wikipedia article titles (not URLs).
8. key_entities: include only entities explicitly mentioned in the article.
```

---

## Switching LLM Providers

Only the `call_llm()` function in `llm_service.py` needs to change. Everything else (prompt templates, JSON parsing, validation) stays the same.

### Switch to Gemini Pro (paid, higher limits)

Change one line in `llm_service.py`:
```python
GEMINI_MODEL = "gemini-1.5-pro"   # was "gemini-1.5-flash"
```

### Switch to Gemini 2.0 Flash (latest free tier)

```python
GEMINI_MODEL = "gemini-2.0-flash"
```

### Switch back to Anthropic Claude

Replace the `call_llm()` body in `llm_service.py`:

```python
async def call_llm(system_prompt: str, user_prompt: str) -> str:
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
```

### Switch to OpenAI

```python
async def call_llm(system_prompt: str, user_prompt: str) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    return resp.choices[0].message.content
```

---

## Features

- ✅ Wikipedia scraping (BeautifulSoup, no Wikipedia API needed)
- ✅ Gemini free-tier quiz generation (7–10 questions, 3 difficulty levels)
- ✅ Key entity extraction (people, organizations, locations)
- ✅ Related topics suggestion
- ✅ PostgreSQL persistence (SQLite auto-fallback for local dev)
- ✅ URL caching — same URL returns stored result instantly
- ✅ Raw HTML storage in DB for reference
- ✅ Tab 1: Generate Quiz with structured card UI
- ✅ Tab 2: History table with Details modal
- ✅ **Take Quiz mode** — answers hidden, submit for score
- ✅ URL preview — fetches article title before full processing
- ✅ Section-wise display + entity chips

---

## Testing Steps

1. Start backend: `uvicorn main:app --reload`
2. Open `index.html` in your browser
3. Paste `https://en.wikipedia.org/wiki/Alan_Turing` and click Generate
4. View quiz cards, difficulty badges, explanations, and related topics
5. Switch to **Take Quiz** mode, answer all questions, submit for score
6. Visit **History** tab to see the saved quiz
7. Click **View** to open the Details modal
8. Paste the same URL again — notice instant cached response
9. Test an invalid URL (`https://example.com`) — observe the error message

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Non-Wikipedia URL | 400 with descriptive message |
| Unreachable URL | 400 with network error message |
| Page has no content | 400 with scraping error |
| Gemini rate limit hit | 500 with "wait and retry" message |
| LLM returns malformed JSON | 500 with retry suggestion |
| DB connection failure | 500 with connection error |
| Quiz not found by ID | 404 |

---

## Troubleshooting

**`GEMINI_API_KEY is not set`**  
→ Make sure you created a `.env` file and added your key. Run `source .env` or restart uvicorn after editing.

**HTTP 429 from Gemini**  
→ You've hit the free-tier rate limit (15 req/min). Wait 60 seconds and try again.

**`JSON parse error`**  
→ Rare — retry the request. Caused by the model occasionally producing non-JSON output despite the JSON mode setting.

**Frontend can't reach backend**  
→ Make sure uvicorn is running on port 8000 and there are no firewall rules blocking localhost.
