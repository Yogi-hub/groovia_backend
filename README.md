# Groovia — AI Career & Study Consulting Engine

Groovia is an agentic AI backend that maps a user's resume to optimal global career or study destinations using real-time search data. It is built with LangGraph (reflection pattern), served via FastAPI, and containerised with Docker.

The frontend (Streamlit) communicates with the backend exclusively through the REST API. This repo contains only the backend.

---

## Architecture

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant UI as app.py
    participant API as main.py
    participant Graph as backend.py
    participant Groq as Groq API
    participant Search as Exa / Tavily

    U->>UI: Upload resume + message
    UI->>API: POST /chat :8000 (multipart/form-data)
    API->>API: Validate UUID, file size
    API->>API: Parse PDF/DOCX → plain text

    API->>Graph: ainvoke(input_state, thread_id)

    Note over Graph: router_node
    Graph->>Groq: Classify intent (ROUTER_PROMPT)
    Groq-->>Graph: EXA or TAVILY

    Note over Graph: compressor_node
    Graph->>Groq: Compress resume (COMPRESSION_PROMPT)
    Groq-->>Graph: Dense resume summary

    Note over Graph: agent_node
    Graph->>Groq: Draft response (SYSTEM_PROMPT + context)
    Groq-->>Graph: Tool call request

    alt TAVILY
        Graph->>Search: career_market_search(query)
    else EXA
        Graph->>Search: neural_research_tool(query)
    end
    Search-->>Graph: Results

    Graph->>Groq: Finalize draft with results
    Groq-->>Graph: Country report draft

    Note over Graph: reviewer_node
    Graph->>Groq: Audit draft (REVIEWER_PROMPT)
    Groq-->>Graph: PASSED or critique

    alt revision_count < MAX_REVISION and not PASSED
        Graph->>Groq: Revise with critique
        Groq-->>Graph: Revised report
    end

    Graph-->>API: final_state
    API-->>UI: 200 OK + JSON
    UI-->>U: Display report
```

---

## Project Structure

```
├── main.py          # FastAPI app — request handling, file parsing, session routing
├── backend.py       # LangGraph graph — nodes, edges, reflection loop
├── utils.py         # Tool definitions (Tavily, Exa) and file parsers
├── prompts.py       # All LLM prompt templates
├── config.py        # Environment variables and model settings
├── schema.py        # Pydantic request/response models
├── Dockerfile
├── docker-compose.yaml
└── .env             # Not committed — see Environment Variables below
```

---

## API

### `POST /chat`

Accepts a user message and optional resume file. Maintains conversation state across turns using `thread_id`.

**Form fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `message` | `string` | Yes | User's message |
| `thread_id` | `string (UUID)` | Yes | Persistent session identifier |
| `file` | `file` | No | PDF or DOCX resume (max 5MB) |

**Response**

```json
{
  "status": "success",
  "response": "...",
  "thread_id": "uuid"
}
```

**Error codes**

| Code | Reason |
|---|---|
| 400 | Invalid `thread_id` format |
| 413 | File exceeds 5MB limit |
| 504 | Agent timed out (> 120s) |
| 500 | Internal agent error |

### `GET /health`

Returns `{"status": "ok"}`. Used by Docker and Render for readiness checks.

---

## Agent Graph

The graph follows a **reflection pattern**:

```
START → router → compressor → agent → tools → agent → reviewer → agent (if rejected) → END
```

| Node | Role |
|---|---|
| `router_node` | Classifies query intent → routes to Exa or Tavily |
| `compressor_node` | Summarises raw resume text once per session |
| `agent_node` | Drafts the career/study report using tools |
| `reviewer_node` | Audits the draft against a quality checklist |

The reviewer rejects and re-queues the draft up to `MAX_REVISION` times before passing it regardless.

---

## Environment Variables

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key
EXA_API_KEY=your_exa_key
```

---

## Running Locally

**Without Docker**

```bash
pip install -r requirements.txt
uvicorn main:api --host 0.0.0.0 --port 8000 --reload
```

**With Docker**

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`.

---

## Configuration

All tunable parameters are in `config.py`:

| Parameter | Default | Description |
|---|---|---|
| `NUM_COUNTRIES` | `3` | Number of countries in the report |
| `MAX_REVISION` | `2` | Max reviewer rejection cycles per response |
| `TEMPERATURE` | `0.0` | LLM temperature |
| `PORT` | `8000` | Server port |

---

## Deployment

The backend is designed to deploy as a single container on Render, Railway, or any Docker-compatible host.

1. Push the repo to GitHub.
2. Create a new **Web Service** on Render, connect the repo.
3. Set the environment variables in the Render dashboard (do not commit `.env`).
4. Render will detect `docker-compose.yaml` or the `Dockerfile` automatically.
5. The `/health` endpoint is used as the health check URL.

> **Note:** `MemorySaver` stores conversation state in-process. A container restart will clear all session history. A persistent checkpointer (Redis or Postgres) is planned for a future release.

---

## Frontend

The Streamlit frontend (`app.py`) is maintained as a separate service and is not included in this container. It communicates with this backend via the `/chat` endpoint using `requests.post`.
