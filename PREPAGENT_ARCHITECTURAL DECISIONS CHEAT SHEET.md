# Architecture Decisions

Engineering design decisions for PrepAgent, with tradeoffs and justifications. Written to be defensible in a technical interview, not to rationalize the README.

---

## 1. Supervisor Graph vs. Fixed Pipeline

### The question

The README describes a "LangGraph supervisor graph with stateful routing across 4 specialized agents" where "the supervisor decides when each agent has gathered sufficient context." But the actual workflow is: research company, research interviewer, retrieve from RAG, synthesize. That's a pipeline. What routing decision is the supervisor actually making?

### Case for a supervisor

A supervisor LLM call between steps could add value if:
- **Retry logic**: Tavily returns zero useful results for a company; the supervisor could reformulate the query and retry before moving on.
- **Conditional skipping**: If no interviewer name is provided, skip the interviewer agent entirely.
- **Quality gating**: The supervisor could evaluate whether research output is rich enough to produce a good briefing, and request more context before synthesis.

The strongest argument is the retry case. Web research is inherently unreliable -- a startup with a common name might return irrelevant results, and a supervisor could catch that.

### Case against a supervisor

- **The workflow is deterministic.** You always need company research, you always attempt interviewer research (or skip it -- a simple `if` statement), and you always synthesize. There's no branching decision that requires LLM judgment.
- **Retry logic belongs inside the agent, not the supervisor.** If the company research agent gets bad Tavily results, the agent itself should reformulate and retry within its tool-calling loop. That's a local decision, not a routing decision.
- **The supervisor call adds latency and cost.** An extra LLM invocation between every step, to make a decision that is almost always "proceed to next step," is overhead with no payoff.
- **A supervisor obscures the actual architecture.** When you say "supervisor graph," an interviewer expects dynamic routing, conditional branching, or agent selection from a pool. If the answer to "what does it route on?" is "nothing, really," the term is misleading.

### Decision: Fixed DAG, not a supervisor

Use LangGraph with explicit edges: Company Research and Interviewer Research run **in parallel** (they're independent), then RAG retrieval, then synthesis. This is still a LangGraph `StateGraph` -- it still demonstrates graph-based orchestration, state management, and LangSmith tracing. But the edges are fixed, which honestly reflects the workflow.

Each research agent internally uses a tool-calling loop with retry logic (reformulate query if Tavily returns <2 results). That handles the "insufficient context" problem without a supervisor.

### Interview answer

> "I initially spec'd a supervisor graph, but when I mapped the actual routing decisions, the workflow is deterministic -- you always research the company, always research the interviewer, and always synthesize. The only dynamic behavior is retry logic when web search returns poor results, and that belongs inside each agent's tool-calling loop, not at the supervisor level. So I use a LangGraph DAG with fixed edges: company and interviewer research run in parallel, then RAG retrieval, then synthesis. I still get LangGraph's state management and LangSmith tracing, but the architecture honestly reflects the workflow instead of adding a supervisor call that would just say 'proceed' every time."

---

## 2. Vector Store: Pinecone vs. pgvector vs. Qdrant

### The question

The README specs Pinecone. I have production experience with Qdrant (SJC project) and pgvector/Supabase (Quizzler). Is there a reason to introduce a third vector store?

### Option A: Pinecone

**Pros**: Fully managed, serverless tier is cheap, good metadata filtering, demonstrates breadth on a resume.

**Cons**: Third vector store I'd need to learn (marginal, but real), adds another API key and service dependency, solves scaling problems that don't exist here. Pinecone's value proposition is high-QPS production search over millions of vectors. PrepAgent's corpus per user is a single resume (~10-20 chunks) and a growing set of briefings (maybe 50-100 over months). That's trivially small.

### Option B: Qdrant

**Pros**: I have production experience, excellent filtering, good performance.

**Cons**: Requires running a separate service (or Qdrant Cloud), already demonstrated in another project so limited portfolio differentiation, overkill for this scale.

### Option C: pgvector via Supabase

**Pros**: Supabase is already in the stack (it's the primary database), so this adds zero new infrastructure. pgvector handles the scale trivially -- we're talking hundreds of vectors, not millions. I have production experience from Quizzler. One fewer API key, one fewer service to monitor, one fewer point of failure. Embeddings live alongside the data they describe (user records, briefings), which simplifies joins and access control.

**Cons**: pgvector is slower than purpose-built vector stores at scale (irrelevant here). Less portfolio differentiation (already used in Quizzler). No built-in hybrid search (but we're not doing keyword + semantic hybrid search anyway).

### Decision: pgvector via Supabase

The corpus is too small to justify a dedicated vector service. A user's resume produces ~15 chunks. After months of use, they might have 50-100 briefing chunks. pgvector handles this without breaking a sweat, and it's already deployed because Supabase is the primary database.

### Interview answer

> "The README originally spec'd Pinecone, but when I sized the actual corpus, it didn't justify a separate vector service. Each user has one resume -- maybe 15 chunks -- and a growing set of briefings that might reach 100 chunks after months of use. Pinecone solves scaling problems I don't have. Since Supabase is already my primary database, pgvector lets me store embeddings alongside user data with zero additional infrastructure. I've shipped pgvector in production before with Quizzler, so I know its limitations -- but those limitations kick in at millions of vectors, not hundreds."

---

## 3. RAG Retrieval Design

### The question

What gets embedded? What gets retrieved? How do you prevent cross-contamination between users or between different company briefings? And does Cohere Rerank actually earn its place?

### What gets embedded

Two document types, chunked differently:

**Resume chunks**: Split by section header -- each job experience entry, education block, skills block, project description. These are naturally 100-300 tokens each. Don't split mid-section; a resume's semantic units are its sections. Each chunk gets metadata: `{user_id, doc_type: "resume", section: "experience|education|skills|projects"}`.

**Briefing chunks**: Split by output section -- company intelligence, interviewer profile, talking points, suggested questions. Each section is a self-contained semantic unit from a prior briefing. Metadata: `{user_id, doc_type: "briefing", company: "Stripe", role: "Senior Backend Engineer", created_at: "2025-07-01"}`.

### Preventing cross-contamination

This is the critical design question. When generating a briefing for Company X, you don't want talking points that reference Company Y's tech stack leaking in.

**Retrieval filter**: Every query uses a `WHERE` clause (pgvector makes this easy since it's just SQL):
- Always filter on `user_id` (users never see each other's data)
- Resume chunks: always retrieved (they're always relevant)
- Briefing chunks: only retrieve where `company = target_company` OR use semantic similarity with a high threshold

The simple version: retrieve all resume chunks (there are only ~15) and only briefings for the same company. This is a SQL filter, not a vector similarity problem. Don't over-engineer it.

### Cohere Rerank: does it earn its place?

**No, not at this scale.** Reranking is valuable when you retrieve 50-100 candidates from a large corpus and need to re-sort them by relevance. With pgvector over <100 total vectors per user, your top-k results are already most of the corpus. Reranking adds latency (~200ms), cost (another API call), and a service dependency for marginal improvement on a tiny retrieval set.

**Decision**: Skip Cohere Rerank. If retrieval quality is poor after launch, add it as a targeted fix. Don't pre-optimize.

### Chunking strategy summary

| Document | Chunking | Typical chunks | Metadata |
|----------|----------|---------------|----------|
| Resume | By section header | 10-20 | user_id, doc_type, section |
| Briefing | By output section | 4 per briefing | user_id, doc_type, company, role, date |

### Interview answer

> "I embed two document types: resume sections and past briefing sections. Resumes are chunked by section header -- each job, education entry, skills block -- because those are natural semantic units. Briefings are chunked by their four output sections. Cross-contamination is prevented at the query level: I always retrieve all resume chunks for the user, but I filter briefing chunks to only the target company. Since I'm using pgvector in Supabase, this is just a SQL WHERE clause alongside the vector similarity search -- no complex metadata filtering API needed. I dropped Cohere Rerank from the design because the corpus per user is under 100 vectors; reranking a retrieval set that's already most of the corpus doesn't add value."

---

## 4. MCP Trigger Detection

### The question

How does the system decide a Gmail message is an interview invite, and how does it extract company and interviewer reliably? What happens when it's wrong?

### Detection approach

The system uses Gmail push notifications (`gmail.watch` API) to receive new messages. The detection pipeline has two stages:

**Stage 1 -- Lightweight pre-filter (no LLM call):** Check for strong signals that don't require understanding the email content:
- Has a calendar invite attachment (`.ics` file or `text/calendar` MIME part)
- Subject line contains scheduling keywords: "interview," "onsite," "phone screen," "technical screen," "schedule," "meet with"
- Sender domain matches a known recruiting platform (Greenhouse, Lever, Ashby, Calendly)

If none of these signals fire, skip the email. This avoids burning an LLM call on every incoming email.

**Stage 2 -- LLM classification and extraction (Claude):** For emails that pass the pre-filter, send the email body to Claude with a structured extraction prompt:

```
Given this email, determine:
1. Is this an interview invitation? (yes/no/uncertain)
2. If yes, extract: company_name, interviewer_name(s), date_time, role_title
3. Confidence: high/medium/low

If uncertain or low confidence, flag for user confirmation.
```

Use structured output (JSON mode) to ensure parseable results.

### Failure modes and their costs

| Failure | Likelihood | Cost | Mitigation |
|---------|-----------|------|------------|
| False positive (sales email flagged as interview) | Medium | Low -- user sees a briefing suggestion, dismisses it | User confirmation step before running the full pipeline |
| False negative (real invite missed) | Low | Medium -- user falls back to manual entry, which always works | Bias the pre-filter toward recall; manual entry is the backstop |
| Wrong company extracted | Low | High -- researches wrong company, wastes a run and produces garbage | Show extracted fields to user for confirmation before running pipeline |
| Wrong interviewer extracted | Medium | Medium -- researches wrong person, talking points are off | Same confirmation step |

**Key insight**: The asymmetry between false positive cost (user clicks "dismiss") and false negative cost (user misses prep) means the pre-filter should bias toward recall. Let more emails through to the LLM classifier rather than fewer.

**Key guardrail**: Never auto-run a briefing from a detected email. Always show the user: "Interview detected: [Company] with [Interviewer] on [Date]. Prepare briefing?" This makes extraction errors cheap.

### Testing

Build a test set of 30 emails:
- 10 real interview invites (vary formats: recruiter, hiring manager, scheduling tool, calendar invite)
- 10 recruiter outreach that are NOT interview invites (sourcing emails, "want to chat" messages)
- 10 unrelated emails (newsletters, receipts, personal)

Measure precision and recall on the classification task. Target: >90% recall (don't miss real invites), >80% precision (some false positives are acceptable given the confirmation step).

### Interview answer

> "Email detection uses two stages: a lightweight pre-filter checks for calendar attachments, scheduling keywords, and known recruiter platform domains -- this avoids an LLM call on every email. Emails that pass go to Claude for structured extraction of company, interviewer, and date. The critical design choice is that we never auto-run a briefing from detection. The user always sees 'Interview detected at [Company] with [Interviewer] -- prepare briefing?' and confirms. This makes both false positives and extraction errors cheap. I tested this against a set of 30 emails across three categories and targeted >90% recall because missing a real invite is more expensive than showing a dismissible false positive."

---

## 5. Eval Design

### The question

The README claims RAGAS across relevance, faithfulness, and context precision, but has no baseline numbers or ground truth set. What's the minimum viable eval?

### Why RAGAS specifically

RAGAS maps well to this task because the three metrics catch three distinct failure modes:

- **Answer relevance**: Does the briefing address *this specific* company and role, or is it generic career advice? Catches the "sounds professional but says nothing" failure.
- **Faithfulness**: Are the talking points grounded in what the research actually found, or did the LLM hallucinate connections between the user's background and the company? Catches the "confidently wrong" failure.
- **Context precision**: Is the retrieved context (resume chunks, past briefings) actually useful for this briefing, or did retrieval surface irrelevant content? Catches RAG retrieval failures.

### What a minimal ground truth set looks like

RAGAS requires four inputs per example: `question`, `answer`, `contexts`, `ground_truth`.

For PrepAgent:
- `question` = "Prepare a briefing for [Company] [Role] interview with [Interviewer] given [resume]"
- `answer` = the generated briefing
- `contexts` = the chunks retrieved from pgvector
- `ground_truth` = a manually written or manually verified "golden" briefing

**Minimum set: 5 examples.** Pick 5 real companies (ideally ones you've actually interviewed at, so you can verify the output). For each:
1. Provide the input (company, role, interviewer name, your resume)
2. Manually write a 1-paragraph golden answer for each of the 4 sections (what a good briefing should contain)
3. Run the pipeline end-to-end
4. Score with RAGAS

### The smallest version you could build and run

```python
# eval_briefings.py
from ragas import evaluate
from ragas.metrics import answer_relevancy, faithfulness, context_precision
from datasets import Dataset

eval_data = {
    "question": [...],      # 5 briefing requests
    "answer": [...],        # 5 generated briefings
    "contexts": [...],      # 5 lists of retrieved chunks
    "ground_truth": [...],  # 5 manually written golden briefings
}

dataset = Dataset.from_dict(eval_data)
results = evaluate(dataset, metrics=[answer_relevancy, faithfulness, context_precision])
print(results)
```

That's ~30 lines of code plus the manual work of writing 5 golden briefings. The golden briefings are the hard part -- each one is maybe 20 minutes of research and writing. So the full eval is roughly a 2-hour effort for 5 examples.

### What "good" looks like

Without running this, reasonable targets based on similar RAG eval benchmarks:
- Answer relevancy: >0.8 (briefing addresses the specific company/role)
- Faithfulness: >0.85 (talking points are grounded in research, not hallucinated)
- Context precision: >0.7 (retrieved chunks are actually relevant)

These are starting baselines, not production targets. The value is in tracking them across prompt iterations, not in the absolute numbers.

### Interview answer

> "I use RAGAS with three metrics that each catch a different failure mode: answer relevance catches generic briefings, faithfulness catches hallucinated talking points, and context precision catches bad retrieval. My ground truth set is 5 examples -- I picked companies I've actually interviewed at so I could verify output quality. Each example has a manually written golden briefing as the reference. The eval script is about 30 lines of Python. My baseline scores are [X, Y, Z] -- the main insight was that faithfulness was the weakest metric because the synthesis agent would sometimes invent connections between my resume and the company that the research didn't actually support, which led me to add source attribution to the synthesis prompt."

---

## 6. Failure Modes and Guardrails

### The question

What's the most likely way this system produces a bad briefing, and what's the cheapest guardrail?

### Ranked failure modes

**1. Hallucinated talking points (highest risk).** The synthesis agent sees your resume mentions "distributed systems" and the company works on "payments infrastructure," and generates a talking point like "Your experience scaling distributed transaction systems directly maps to [Company]'s payment architecture" -- even if your distributed systems experience was in a completely different domain. The LLM connects dots that don't actually connect.

**2. Stale or wrong company information.** Tavily returns a 2-year-old funding announcement, and the briefing presents it as recent news. Or the company name is ambiguous ("Mercury" could be the fintech, the browser, or the planet) and research pulls the wrong entity.

**3. Wrong person for interviewer research.** "John Smith, Engineering Manager" matches many people. The system builds a profile of the wrong John Smith, and your talking points reference their blog posts or conference talks.

**4. Missing relevant resume context.** RAG retrieval misses the most relevant experience section because the embedding similarity between "built real-time data pipelines at [Previous Company]" and "streaming infrastructure role at [Target Company]" isn't high enough. The briefing misses your strongest angle.

### Cheapest guardrails (ordered by cost to implement)

**Guardrail 1: Source attribution in the synthesis prompt (cost: ~0 -- it's a prompt change).**

Add to the synthesis agent's system prompt: "Every factual claim must cite its source. For company facts, include the URL. For resume references, quote the specific section. If you cannot cite a source, do not include the claim."

This doesn't prevent hallucination, but it makes hallucination *detectable*. When the user reads "Your experience with distributed transaction systems [Resume: Senior Engineer at Acme, 2022-2024]" and that job was actually about frontend development, they catch it immediately. Unsourced claims become a visible red flag.

**Guardrail 2: Low-result warnings (cost: a few lines of code).**

If Tavily returns fewer than 3 results for company or interviewer research, flag the section: "Limited public information available for [Interviewer]. The following profile is based on [N] sources and may be incomplete." This sets user expectations and prevents false confidence.

**Guardrail 3: Structured output validation (cost: a JSON schema).**

Use Claude's structured output to enforce that all 4 briefing sections are present and non-empty, that each section contains at least one source citation, and that the talking points reference specific resume sections. This catches structural failures (empty sections, missing citations) programmatically.

**Guardrail 4: Company disambiguation (cost: moderate -- requires an extra LLM call).**

Before running company research, do a quick check: "Given the company name '[X]' and the role '[Y]', identify the most likely company entity and its domain." This prevents the "Mercury fintech vs. Mercury browser" problem. Only worth implementing if ambiguity turns out to be a real issue in practice.

### What NOT to build

- **Human-in-the-loop review before delivery**: The whole point is a 90-second briefing. Adding a review step defeats the value proposition.
- **Automated fact-checking against a knowledge base**: Massively complex, marginal benefit over source attribution.
- **Confidence scores on each section**: Users don't calibrate on confidence scores. Source attribution is more actionable.

### Interview answer

> "The most likely failure is hallucinated talking points -- the synthesis agent invents connections between the user's resume and the target company that the research doesn't actually support. The cheapest guardrail is source attribution in the synthesis prompt: every claim must cite either a URL from the research or a specific resume section. This doesn't prevent hallucination, but it makes it immediately detectable by the user. An unsourced claim is a red flag. I also add low-result warnings -- if Tavily returns fewer than 3 results for the company or interviewer, the section explicitly says 'limited public data available.' These two guardrails are essentially free to implement -- one is a prompt change, the other is a conditional check -- and they address the two highest-risk failure modes."

---

## Summary of changes from the README

| README claims | Actual decision | Reason |
|---|---|---|
| LangGraph supervisor graph | LangGraph fixed DAG (parallel research, then RAG, then synthesis) | No real routing decision; workflow is deterministic |
| Pinecone | pgvector via Supabase | Corpus is <100 vectors per user; Supabase is already in the stack |
| Cohere Rerank | Dropped | Reranking a retrieval set that's already most of the corpus adds cost without value |
| RAGAS evals (no baseline) | RAGAS with 5-example ground truth set | Minimum viable eval with actual numbers to report |
| Supervisor "decides when sufficient context" | Per-agent retry loop with result-count threshold | "Sufficient context" is a local decision (did Tavily return results?), not a routing decision |

These aren't compromises -- they're better-justified decisions. A supervisor graph with no routing logic is harder to defend than a fixed DAG that honestly represents the workflow.
