# PrepAgent

Status: architecture designed, implementation in progress.

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

**Integrations:** Gmail MCP, Google Calendar MCP, Google Drive MCP

**Infrastructure:** Docker, AWS EC2, GitHub Actions CI/CD

## Architecture

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

## Agent Architecture

PrepAgent uses a LangGraph DAG with fixed edges. Company research and interviewer research run in parallel (they're independent), then RAG retrieval pulls relevant resume and briefing context, then synthesis generates the final briefing. Retry logic for insufficient web results lives inside each agent's tool-calling loop rather than in a separate routing layer.

Each agent step is traced in LangSmith. Every tool call is logged with token usage and latency.

## Evaluation

PrepAgent uses RAGAS to evaluate briefing quality across 3 metrics:

- **Answer relevance** — does the briefing address this specific role and company
- **Faithfulness** — are talking points grounded in what the research actually found
- **Context precision** — is the retrieved context from pgvector useful for this briefing

Baseline scores are documented and tracked across prompt iterations.

## License

MIT
