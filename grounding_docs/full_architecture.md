Superseded — see ARCHITECTURE_DECISIONS.md for the current design and reasoning.

Let me lay out the complete architecture before we go into the week by week spec.

Full System Architecture
prepagent.app (Next.js on Vercel)
        ↓
FastAPI Backend (AWS EC2 / GCP Cloud Run)
        ↓
LangGraph Supervisor Graph
    ├── Company Intelligence Agent (Tavily MCP)
    ├── Interviewer Research Agent (Tavily MCP)
    ├── RAG Retrieval Agent (Pinecone + Cohere Rerank)
    └── Synthesis Agent (Claude Sonnet)
        ↓
Gmail MCP + Google Calendar MCP (OAuth)
Google Drive MCP (briefing storage)
Supabase PostgreSQL (users, briefings, tokens)
LangSmith (tracing every agent step)
RAGAS (briefing quality evals)
GitHub Actions (CI/CD)
Docker (containerization)


Folder Structure
prepagent/
├── frontend/                    # Next.js app
│   ├── app/
│   │   ├── page.tsx             # landing page
│   │   ├── dashboard/           # briefing history
│   │   ├── briefing/[id]/       # briefing viewer
│   │   └── api/                 # Next.js API routes for auth
│   ├── components/
│   └── lib/
├── backend/                     # FastAPI
│   ├── main.py                  # app entry point
│   ├── routers/
│   │   ├── research.py          # POST /research
│   │   ├── runs.py              # GET /runs/{id}
│   │   └── auth.py              # OAuth token management
│   ├── agents/
│   │   ├── supervisor.py        # LangGraph graph definition
│   │   ├── company.py           # Company Intelligence Agent
│   │   ├── interviewer.py       # Interviewer Research Agent
│   │   ├── rag.py               # RAG Retrieval Agent
│   │   └── synthesis.py         # Synthesis Agent
│   ├── services/
│   │   ├── gmail.py             # Gmail MCP integration
│   │   ├── calendar.py          # Calendar MCP integration
│   │   ├── drive.py             # Drive MCP briefing storage
│   │   ├── pinecone.py          # vector store operations
│   │   └── eval.py              # RAGAS scoring
│   ├── models/
│   │   ├── briefing.py          # Pydantic schemas
│   │   └── user.py              # Pydantic schemas
│   └── Dockerfile
├── .github/
│   └── workflows/
│       └── ci.yml               # GitHub Actions
├── docker-compose.yml
└── README.md


Database Schema (Supabase)
Four tables. Simple and defensible.
-- users
create table users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  google_access_token text,
  google_refresh_token text,
  resume_text text,
  pinecone_namespace text,  -- user-specific namespace
  created_at timestamptz default now()
);

-- briefings
create table briefings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id),
  company text not null,
  role text,
  interviewer text,
  interview_date text,
  status text default 'pending',  -- pending, running, complete, failed
  content jsonb,                  -- structured briefing output
  ragas_scores jsonb,             -- eval scores
  langsmith_run_id text,          -- link back to trace
  created_at timestamptz default now()
);

-- research_runs
create table research_runs (
  id uuid primary key default gen_random_uuid(),
  briefing_id uuid references briefings(id),
  agent text not null,           -- company, interviewer, rag, synthesis
  status text default 'pending',
  output jsonb,
  started_at timestamptz,
  completed_at timestamptz
);

-- gmail_watches (for v2 auto-trigger)
create table gmail_watches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id),
  watch_expiry timestamptz,
  active boolean default true
);


LangGraph Supervisor Graph
This is the core of the system and the piece you defend in every interview.
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Optional

class ResearchState(TypedDict):
    # inputs
    company: str
    role: str
    interviewer: Optional[str]
    interview_date: Optional[str]
    user_resume: str
    
    # accumulated research
    company_intelligence: Optional[dict]
    interviewer_profile: Optional[dict]
    rag_context: Optional[List[dict]]
    
    # control flow
    research_complete: bool
    synthesis_complete: bool
    
    # output
    briefing: Optional[dict]
    ragas_scores: Optional[dict]

def build_graph():
    graph = StateGraph(ResearchState)
    
    # nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("company_agent", company_intelligence_node)
    graph.add_node("interviewer_agent", interviewer_research_node)
    graph.add_node("rag_agent", rag_retrieval_node)
    graph.add_node("synthesis_agent", synthesis_node)
    graph.add_node("eval_agent", ragas_eval_node)
    
    # edges -- supervisor routes based on state
    graph.add_conditional_edges(
        "supervisor",
        route_research,
        {
            "company": "company_agent",
            "interviewer": "interviewer_agent",
            "rag": "rag_agent",
            "synthesize": "synthesis_agent",
            "eval": "eval_agent",
            "complete": END
        }
    )
    
    # all agents report back to supervisor
    graph.add_edge("company_agent", "supervisor")
    graph.add_edge("interviewer_agent", "supervisor")
    graph.add_edge("rag_agent", "supervisor")
    graph.add_edge("synthesis_agent", "supervisor")
    graph.add_edge("eval_agent", "supervisor")
    
    graph.set_entry_point("supervisor")
    return graph.compile()

def route_research(state: ResearchState) -> str:
    # supervisor routing logic -- this is what you defend in interviews
    if not state.get("company_intelligence"):
        return "company"
    if state.get("interviewer") and not state.get("interviewer_profile"):
        return "interviewer"
    if not state.get("rag_context"):
        return "rag"
    if not state.get("briefing"):
        return "synthesize"
    if not state.get("ragas_scores"):
        return "eval"
    return "complete"

The routing logic is what interviewers ask about. Your answer: "Company research and RAG retrieval can theoretically run in parallel but I kept them sequential in v1 because the synthesis agent needs all three complete before it can run, and the added complexity of parallel execution wasn't justified by the latency savings at this scale. In v2 I'd parallelize company and interviewer research since they're independent."
That's a real architectural tradeoff you can defend.

Week by Week Build Spec
15 hours per week, 5 days x 3 hours.

Week 1 -- Foundation and Auth
Goal: User can sign in with Google, upload resume, see empty dashboard.
Day 1 (3 hrs): Project setup
Initialize Next.js frontend and FastAPI backend as monorepo
Set up Supabase project, run schema migrations
Set up Google Cloud Console app, enable Gmail and Calendar APIs
Submit for OAuth verification immediately -- clock starts today
Day 2 (3 hrs): Google OAuth flow
Implement OAuth in FastAPI -- auth router, token exchange, refresh logic
Store access and refresh tokens in Supabase users table
Test the full OAuth round trip locally
Day 3 (3 hrs): Next.js auth integration
Sign in with Google button on landing page
Session management using Supabase auth
Redirect to dashboard after OAuth completes
Day 4 (3 hrs): Resume ingestion
Resume upload UI in Next.js -- PDF upload or text paste
FastAPI endpoint receives resume, chunks it, embeds via OpenAI text-embedding-3-small
Stores embeddings in Pinecone under user-specific namespace
Saves raw resume text to Supabase users table
Day 5 (3 hrs): Dashboard shell
Dashboard page showing empty briefing history
"New Briefing" button that opens a form
FastAPI health check, Docker setup begun
GitHub Actions CI pipeline -- runs on every push, fails loudly
Week 1 end state: User visits prepagent.app, signs in with Google, uploads resume, sees their dashboard. Nothing else works yet. But auth and resume ingestion are production-ready.

Week 2 -- Research Pipeline
Goal: Given company and interviewer, all three research agents run and return structured output.
Day 1 (3 hrs): Tavily MCP + Company Intelligence Agent
Wire up Tavily MCP server
Company Intelligence Agent: searches for recent news, funding, engineering blog posts, job postings
Returns structured CompanyIntelligence Pydantic model
LangSmith tracing connected -- every tool call logged
Day 2 (3 hrs): Interviewer Research Agent
Tavily searches for interviewer's public presence -- LinkedIn data, writing, talks, GitHub
Returns structured InterviewerProfile Pydantic model
Overlap analysis: cross-reference interviewer background against user resume from Supabase
Day 3 (3 hrs): RAG Retrieval Agent
Query Pinecone with company name and role as query
Retrieve top 20 chunks from user's resume namespace
Cohere Rerank re-scores against the specific query, returns top 5
Returns ranked context chunks with relevance scores
Day 4 (3 hrs): LangGraph supervisor graph
Wire all three agents into the StateGraph
Implement route_research supervisor logic
Test full research run end to end -- all three agents complete, state accumulated correctly
LangSmith trace shows all agent steps
Day 5 (3 hrs): FastAPI research endpoints
POST /research -- accepts company, role, interviewer, date, triggers graph
GET /runs/{run_id}/status -- returns current agent progress
GET /runs/{run_id}/results -- returns raw research output
Frontend progress display connected to status endpoint via polling
Week 2 end state: User fills in the New Briefing form, clicks submit, watches live progress as each agent completes, sees raw research output. Not yet synthesized into a briefing.

Week 3 -- Synthesis, Evals, Briefing Viewer
Goal: Full pipeline produces a polished briefing. RAGAS evals running. Briefing renders beautifully in browser.
Day 1 (3 hrs): Synthesis Agent -- first pass
Takes all three research outputs plus user resume
Claude Sonnet generates four-section briefing
Returns structured Briefing Pydantic model with company intelligence, interviewer profile, talking points, questions sections
Saves to Supabase briefings table
Day 2 (3 hrs): Synthesis prompt iteration
Run pipeline on 5 real companies you've actually applied to
Read every output critically -- are talking points genuinely specific or generic?
Iterate the synthesis prompt until talking points reference specific details from research
This is the highest-leverage day in the entire project
Day 3 (3 hrs): RAGAS eval suite
Build ground truth dataset of 10 manually labeled briefings -- score each section as good, acceptable, or poor
Implement RAGAS scoring: answer relevance, faithfulness, context precision
GET /runs/{run_id}/eval endpoint returns RAGAS scores
Document baseline scores
Day 4 (3 hrs): Briefing viewer UI
Render briefing in Next.js with clean four-section layout
Copy button for each section
RAGAS quality indicators shown subtly per section
Link to LangSmith trace for technical users
Google Drive save button -- saves formatted briefing to Drive via Drive MCP
Day 5 (3 hrs): Google Drive MCP integration + dashboard
Drive MCP saves completed briefing as formatted Google Doc
Dashboard shows briefing history with company, date, status
Click any briefing to open the viewer
Brief loading states, error states handled cleanly
Week 3 end state: Full pipeline works. User fills form, briefing generates in 90 seconds, renders in browser, saves to Drive. RAGAS scores documented. This is your v1 -- deployable right now if needed.

Week 4 -- Deploy, Polish, Launch
Goal: Live at prepagent.app with real users.
Day 1 (3 hrs): Docker + cloud deployment
Finalize Dockerfile for FastAPI backend
Deploy to AWS EC2 or GCP Cloud Run
Environment variables via dotenv, never hardcoded
Frontend deployed to Vercel -- one command
Day 2 (3 hrs): Production hardening
Rate limiting on research endpoints -- one concurrent run per user
Error handling for all failure modes -- Tavily timeout, Pinecone error, Cohere error
Graceful degradation -- if interviewer research fails, briefing still generates from company research and RAG
Retry logic with exponential backoff on all external API calls
Day 3 (3 hrs): Landing page and onboarding
Landing page that explains the product clearly in 30 seconds
Onboarding flow that gets users to their first briefing in under 5 minutes
Privacy policy and terms of service -- required for Google OAuth verification
Demo video recorded -- 90 second screen recording of a full briefing generation
Day 4 (3 hrs): README and LinkedIn content
README that reads like a technical blog post -- architecture decisions, why you chose each component, what you'd do differently
First LinkedIn post written and scheduled: "I built an AI agent that preps me for interviews automatically. Here's the 4-agent MCP architecture."
Product Hunt draft prepared
Day 5 (3 hrs): Launch
Post on r/cscareerquestions
Post on LinkedIn
Submit to Product Hunt
Post on Hacker News Show HN
Share in any job seeker Discords or Slacks you're in
Week 4 end state: Live, deployed, real users, first LinkedIn post published, launch underway.

The one thing to do on day one before anything else
Go to Google Cloud Console right now, create the PrepAgent app, enable the Gmail API, Calendar API, and Drive API, and submit the OAuth verification request. The verification takes 1-4 weeks. If you wait until week 3 to submit it, you'll be stuck in testing mode -- limited to 100 whitelisted users -- when you want to launch.
Submit today. Build while it processes.

Ready to start day 1?

