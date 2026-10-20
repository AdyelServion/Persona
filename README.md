# Sarah Taylor Persona Runtime

Persistent fictional virtual human MVP. MongoDB is the source of truth for persona, memory, state, and relationships. LangGraph orchestrates each turn. The LLM generates language and structured decisions only.

## Requirements

- Python 3.11+
- MongoDB Atlas URI in `.env`
- OpenAI API key and model in `.env`

## Environment

Required variables in `.env` (never commit this file; use `.env.example` as a template):

```
MONGODB_URI=...
DB_NAME=Sarah
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Optional:

```
NGROK_KEY=...
DEFAULT_PERSONA_ID=sarah_taylor_001
DEFAULT_USER_ID=local-user
FASTAPI_BASE_URL=http://127.0.0.1:8001
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=true
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Ingest persona markdown

```powershell
python scripts\ingest_persona.py
```

This parses the category `.md` files into the MongoDB `Identity` collection (one document per subcategory), seeds canonical facts, autobiographical/life-event memories, named relationships, and default persona state.

## Run API (FastAPI)

```powershell
python scripts\run_api.py
```

API listens on `http://127.0.0.1:8001`

- `GET /health`
- `POST /api/conversations`
- `GET /api/conversations/{id}/messages`
- `POST /api/conversations/{id}/messages`
- `POST /api/conversations/{id}/opening`
- `POST /api/events/message_seen`

## Run chat UI (Django)

In a second terminal:

```powershell
python manage.py runserver 8000
```

Open `http://127.0.0.1:8000`

Django proxies chat calls to FastAPI. Secrets never reach the browser.

## Deploy on Render

The public site is Django on Render's `$PORT`. FastAPI runs on `127.0.0.1:8001` in the same service. Django proxies chat calls so API keys never reach the browser.

1. Confirm `.env`, `.venv/`, and `.venv311/` are **not** uploaded. They are in `.gitignore`.
2. Push this repo to a public GitHub repository. Rotate MongoDB, OpenAI, and ngrok keys if they were ever committed or shared.
3. In MongoDB Atlas → Network Access, allow `0.0.0.0/0` (or Render's outbound IPs) so the service can reach the cluster.
4. In the [Render dashboard](https://dashboard.render.com), create a Blueprint from the repo (it reads `render.yaml`) **or** a Python Web Service with:
   - **Build:** `pip install -r requirements.txt && python manage.py collectstatic --noinput`
   - **Start:** `python scripts/start_web.py`
5. Set secret env vars in Render (never in git):
   - `MONGODB_URI`
   - `OPENAI_API_KEY`
   - `DJANGO_SECRET_KEY` (Blueprint generates this)
6. After the first deploy, seed persona data once if the database is empty:
   - Render Shell: `python scripts/ingest_persona.py`
   - Or set `RUN_INGEST_ON_START=true` for a single deploy, then turn it off.

Open the `*.onrender.com` URL. Health check: `GET /health`.

## Optional ngrok (dev)

With Django running:

```powershell
python scripts\run_ngrok.py
```

## Architecture (summary)

1. Event router
2. Hydrate identity / state / relationship / user context
3. Retrieve typed memories (scoped)
4. Interpret turn (question slots + optional subcategory gap)
5. Behaviour decision (JSON)
6. Response plan with grounded answer plan + evidence guard
7. Response generation (ANSWER_PLAN when present; multi-bubble JSON)
8. Recall claim check (no fabricated memories)
9. Persist + memory consolidation

Static personality and dynamic state are separate. Generated subcategories are persisted with provenance and rejected on canonical conflicts.

Factual questions are answered from database-backed facts with status (`established` / `simulated` / `inferred` / `unknown` / `outdated`). An authoritative Europe/London clock and persisted `TimelineEvents` drive world state; the model never invents the date or time. Simulated experience details (e.g. current meal) are materialised for the open activity window and closed on timeline transitions. See [memory.md](memory.md) and [docs/timeline.md](docs/timeline.md).

## Tests

```powershell
pytest -q
```

Persona consistency QA (isolated `qa-*` users, Mongo suite store, reports under `qa_reports/`):

```powershell
python -m persona_runtime.qa seed --write-json
python -m persona_runtime.qa run --test-key PROFILE-003
```

See [docs/persona_qa.md](docs/persona_qa.md).

Integration against live Mongo (optional):

```powershell
pytest -q -m integration
```

## Notes

- Sarah Taylor is fictional.
- Do not hard-code the OpenAI model name; `OPENAI_MODEL` is read from the environment.
- The same LangGraph runtime accepts `persona_id` for future personas.
