# PrepAgent

AI-powered interview research. Enter a company and interviewer — get a personalized briefing in 90 seconds.

## What it does

PrepAgent runs a 4-agent research pipeline when you have an interview:

1. **Company Intelligence Agent** — finds recent news, funding, engineering blog posts, and job posting patterns
2. **Interviewer Research Agent** — builds a profile of who you're meeting and finds overlap with your background
3. **RAG Retrieval Agent** — queries your indexed resume and past briefings for relevant context
4. **Synthesis Agent** — generates a personalized briefing with talking points specific to your background

The output is a 4-section briefing: company intelligence, interviewer profile, your talking points, and questions to ask.


## Tech Stack

**Frontend:** Next.js, TypeScript, Tailwind CSS, Supabase Auth

**Backend:** FastAPI, Python 3.12, LangGraph, LangChain, Claude Sonnet

**Database:** Supabase PostgreSQL

**Vector Store:** pgvector (Supabase)

**Observability:** LangSmith 

**Evals:** RAGAS 

**Integrations:** Google OAuth (built); Gmail, Google Calendar, and Google Drive MCP )

**Infrastructure:** Docker Compose and GitHub Actions CI (built); AWS EC2 / Vercel deployment 

## Target Architecture

```
Next.js Frontend (Vercel)
    ↓
FastAPI Backend (AWS EC2)
    ↓
LangGraph DAG
    ├── Company Intelligence Agent (Tavily) ──┐ parallel
    ├── Interviewer Research Agent (Tavily) ──┘
    ↓
    ├── RAG Retrieval Agent (pgvector)
    ↓
    └── Synthesis Agent (Claude Sonnet)
    ↓
Gmail MCP + Google Calendar MCP + Google Drive MCP
Supabase PostgreSQL
LangSmith Tracing
```

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 18+
- Accounts: Anthropic, OpenAI, Supabase, LangSmith, Tavily

### Backend Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in your API keys
uvicorn main:app --reload
```

### Frontend Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
# fill in your Supabase keys
npm run dev
```

### Environment Variables

**backend/.env**

```bash
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=prepagent
TAVILY_API_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
FRONTEND_URL=http://localhost:3000
```

**frontend/.env.local**

```bash
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Agent Architecture (design)

PrepAgent will use a LangGraph DAG with fixed edges. Company research and interviewer research run in parallel (they're independent), then RAG retrieval pulls relevant resume and briefing context, then synthesis generates the final briefing. Retry logic for insufficient web results lives inside each agent's tool-calling loop rather than in a separate routing layer.


## Key Design Decisions

Full reasoning is in [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) and [docs/decisions.md](docs/decisions.md).

- **Fixed DAG, not a supervisor.** The workflow is deterministic, so a routing LLM call adds latency and cost for no benefit. Retries live inside each agent.
- **pgvector over Pinecone/Qdrant.** The corpus is about 15 resume chunks plus a small set of briefing chunks per user, and Supabase is already in the stack.
- **No reranker.** Retrieval is a SQL filter scoped by `user_id` and company, because the candidate set is already most of the corpus.
- **Cross-contamination prevention.** Briefing chunks are filtered to the target company so other companies' details don't leak into talking points.
- **Guardrails for hallucination.** Source attribution in synthesis and low-result warnings .
- **Identity from the JWT only**, never the request body.

## Engineering Workflow

Spec-first (Given/When/Then acceptance criteria in `specs/`), tests written before implementation, and conventional commits.

## Evaluation 

PrepAgent will use RAGAS to evaluate briefing quality across 3 metrics:

- **Answer relevance** — does the briefing address this specific role and company
- **Faithfulness** — are talking points grounded in what the research actually found
- **Context precision** — is the retrieved context from pgvector useful for this briefing

## License

MIT
