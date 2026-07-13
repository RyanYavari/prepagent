PrepAgent
The one-liner: An AI agent that researches your interview automatically and delivers a personalized briefing in 90 seconds -- so you walk into every conversation knowing exactly what to say.

The problem
You get an interview invite. The call is in 48 hours. You open six tabs: the company website, their engineering blog, a TechCrunch article about their last funding round, the interviewer's LinkedIn, their GitHub, and a Glassdoor page. Forty-five minutes later you have a Google Doc full of notes you'll half-read the morning of the call.
Every candidate does this. The ones who stand out aren't the ones who researched more -- they're the ones whose research was more specific. They know the interviewer led a latency optimization project last quarter. They know the company just shifted their infrastructure focus based on a blog post from last month. They ask questions that make the interviewer think "this person actually prepared."
The problem isn't access to information. It's synthesis. You can find everything. You just can't process it all into specific, actionable talking points in the 48 hours you have.

The product
PrepAgent lives at prepagent.app. Sign in with Google, upload your resume, and you're set up in under 5 minutes.
When you have an interview, you open the dashboard, click New Briefing, and fill in three fields: company name, role, and the interviewer's name if you have it. That's it. You click Generate.
90 seconds later your briefing is ready -- rendered in the browser, saved to your Google Drive, and structured into four sections that tell you exactly what to say and ask.
Section 1 -- The company right now
Not what their homepage says. What they're actually focused on this quarter. Recent funding, product launches, engineering blog posts from the last 90 days, and job posting patterns that reveal strategic priorities a generic candidate would never surface.
Section 2 -- The person you're meeting
Their career trajectory, what they worked on before this company, any public writing or talks, GitHub activity if public, and the specific intersection between their background and yours.
Section 3 -- Your talking points
This is what no other tool does. Three to five specific connection points between your background -- your projects, your experience, your specific technical decisions -- and this company's current priorities. Not generic STAR answers. Specific bridges: "Your March engineering blog post about context window optimization connects directly to the latency work I did at SJC -- specifically why I chose semantic caching over naive retrieval."
Section 4 -- Questions to ask
Two or three questions that signal unusually deep research. Not "what does success look like in this role." Questions that reference specific things PrepAgent found: "I saw your team is migrating to a microservices architecture -- how has that affected your approach to agent orchestration?"

The MCP architecture
PrepAgent connects to Gmail, Google Calendar, and Google Drive via MCP through a single Google OAuth flow. User clicks "Sign in with Google," authorizes once, and all three integrations are live.
Gmail MCP -- in v2, monitors your inbox and automatically detects interview invites, extracting company, interviewer, role, and date without you doing anything. Briefing is ready before you've finished reading the email.
Google Calendar MCP -- reads calendar invites for additional prep context -- meeting title, prep links the recruiter included, scheduled time for appropriate briefing lead time.
Google Drive MCP -- saves every completed briefing as a formatted Google Doc in a dedicated PrepAgent folder. Every company you've researched is archived. When you interview at the same company again, PrepAgent checks your history first and uses it as additional context.
These integrations aren't convenience features. They're what transforms PrepAgent from a research tool you have to remember to use into an agent that prepares you automatically.

The 4-agent LangGraph architecture
A LangGraph supervisor graph orchestrates four specialized agents:
Company Intelligence Agent uses Tavily MCP to search for recent news, funding announcements, product launches, engineering blog posts, and job posting patterns. Queries are generated dynamically based on company name and role type. Returns a structured CompanyIntelligence object.
Interviewer Research Agent searches for the interviewer's public presence -- LinkedIn data, public writing, conference talks, GitHub activity. Cross-references their background against your resume to identify genuine connection points. Returns a structured InterviewerProfile object with overlap analysis.
RAG Retrieval Agent queries Pinecone for your indexed background -- resume, past briefings, any context you've added. Uses Cohere Rerank to re-score retrieved chunks against the specific query, pushing the most decision-relevant context to the top. Returns ranked chunks with relevance scores.
Synthesis Agent takes all three research outputs plus your background and generates the four-section briefing using Claude Sonnet. It doesn't summarize what it found -- it reasons about the intersection between your specific background and their specific current priorities.
The supervisor node routes between agents based on accumulated state, decides when enough context has been gathered to synthesize, and handles failures gracefully -- if interviewer research fails, the briefing still generates from company research and RAG alone.
The routing logic is the most defensible engineering decision in the system. In v1 agents run sequentially. In v2 company and interviewer research run in parallel since they're independent, cutting latency by roughly 40%.

The RAG pipeline
Your resume and background are indexed into Pinecone on signup. Every briefing generated is indexed after delivery, creating a growing personal knowledge base.
The pipeline:
Resume ingested and chunked on prepagent init with deliberate overlap to preserve context across section boundaries
Embedded via OpenAI text-embedding-3-small
Stored in Pinecone under a user-specific namespace
At retrieval time: semantic search returns top 20 chunks
Cohere Rerank re-scores against the specific query, returns top 5
Top 5 chunks injected into synthesis agent prompt
The reranking step is specifically defensible: you're retrieving from heterogeneous sources -- resume sections, past briefings, indexed prep notes -- and pure vector similarity doesn't account for query-specific relevance. Reranking fixes that precision problem at the cost of one additional API call, which is the right tradeoff.

Observability and evals
Every agent step traced in LangSmith. Every tool call logged. Token usage per run. Cost per briefing. Prompt versions tracked so quality changes are measurable across iterations.
RAGAS eval suite on 20 ground truth briefings manually labeled as high or low quality:
Answer relevance -- does the briefing actually address this specific role and company
Faithfulness -- are talking points grounded in what the research actually found
Context precision -- is the retrieved context from Pinecone actually useful for this briefing
Baseline scores documented before and after every significant prompt change. When the synthesis prompt is updated, RAGAS tells you whether quality went up or down. That's the eval discipline that separates a production system from a demo.

The tech stack
LangGraph -- supervisor graph managing 4-agent orchestration with stateful routing
Claude Sonnet -- synthesis agent reasoning over research outputs
Pinecone -- user-specific vector namespaces for resume and briefing history
Cohere Rerank -- precision optimization over heterogeneous retrieved context
OpenAI text-embedding-3-small -- document embeddings
LangSmith -- full pipeline tracing, token usage, cost per run
RAGAS -- briefing quality evals with documented baselines
FastAPI + Pydantic v2 -- REST API with structured output validation at every agent boundary
Next.js -- frontend dashboard, briefing viewer, onboarding flow
Supabase -- users, briefings, OAuth tokens, research run history
Gmail MCP -- invite detection and email context extraction
Google Calendar MCP -- invite context and scheduling information
Google Drive MCP -- briefing archival and historical context retrieval
Tavily MCP -- web search for company and interviewer research
Docker -- containerized backend from day one
AWS EC2 / GCP Cloud Run -- backend deployment
Vercel -- frontend deployment
GitHub Actions -- CI/CD on every push
Every single component has a reason to exist. None of it is bolted on.

The LinkedIn content flywheel
Post 1: "I built an AI agent that researches my interviews automatically. Here's the 4-agent MCP architecture that makes it work. Thread."
Post 2: "I used PrepAgent on my last 6 interviews. Here's what the briefings looked like, what I would have missed manually, and one moment where it completely changed how I answered a question."
Post 3: "The hardest part of building PrepAgent wasn't the RAG pipeline. It was making the synthesis agent produce talking points that are actually specific to you -- not generic. Here's how I solved it."
Post 4: "How do you evaluate whether an AI research briefing is actually good? Here's the RAGAS eval framework I built and my baseline scores."
Post 5: "Here's the full LangSmith trace from a real PrepAgent run -- 4 agents, every tool call, every token, what it cost, and where the latency lives."
Post 6: "PrepAgent just hit 50 users. Here's what I learned about building AI products for job seekers: what they actually use, what they ignore, and what I'm building next."
Each post is architectural, data-driven, and ends with a link to prepagent.app. The content flywheel runs on your own job search -- every interview you prep for is content.

The interview moment
You tell the interviewer you used PrepAgent to prep for this specific conversation.
You open your laptop and show them the briefing -- the company intelligence section that referenced their engineering blog from last month, the talking points that connect your SJC latency work to their infrastructure challenges, the questions you prepared that reference specific things you found.
Then you open LangSmith and show the trace -- four agents, every tool call logged, every token counted, Cohere reranking scores visible on each retrieved chunk.
Then you show the RAGAS eval dashboard -- answer relevance, faithfulness, context precision scores, baseline versus current after your last prompt iteration.
That's three minutes. That's the complete AI engineering story -- MCP integration, multi-agent orchestration, RAG pipeline with reranking, observability, eval infrastructure, production deployment -- demonstrated live on a system you built and used on them specifically.
No other candidate in the room has that moment.

Resume bullet preview:
Built PrepAgent, a full-stack multi-agent interview research system using LangGraph supervisor architecture with 4 specialized agents, reducing pre-interview research from 45 minutes to 90 seconds for X active users at prepagent.app
Engineered MCP-native integrations with Gmail, Google Calendar, and Google Drive via Google OAuth, enabling autonomous briefing generation triggered by interview invite detection
Implemented RAG pipeline with Pinecone vector store, Cohere Rerank, and OpenAI embeddings, achieving X% answer relevance on RAGAS eval suite across 20 ground truth briefings
Deployed FastAPI backend on AWS EC2 with Docker containerization, Next.js frontend on Vercel, and GitHub Actions CI/CD serving X active users

Resume score: 9/10.
Combined with SJC and Optimal you have three projects telling three different parts of the AI engineering story -- production RAG at scale, multi-agent systems with evals, and MCP-native full-stack deployment. No overlap. No redundancy. Every hiring manager question answered before it's asked.
Ready to start building?

