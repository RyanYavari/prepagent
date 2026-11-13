---
name: quiz
description: Generate interview questions from the codebase to prep for technical interviews
---

# /quiz

Generate interview questions based on the PrepAgent codebase.

## Steps

1. Ask which topic area (or pick based on recent work):
   - System design (LangGraph DAG, RAG pipeline, agent orchestration)
   - Backend (FastAPI, Pydantic, async patterns, dependency injection)
   - Frontend (Next.js app router, React Server Components, Supabase SSR)
   - Infrastructure (Supabase, pgvector, embeddings, CI/CD)
   - AI/ML (prompt engineering, eval design, retrieval strategies)

2. Read relevant source files for the chosen topic.

3. Generate 5 questions in this format:

```markdown
# Quiz: [Topic Area]

## Q1: [Question]
**Context:** [Which file/pattern this relates to]
**What a strong answer covers:**
- [Key point 1]
- [Key point 2]
- [Key point 3]
**Your implementation:** [Reference to specific code in PrepAgent]

## Q2: ...
```

4. Questions should be things an interviewer would actually ask:
   - "Walk me through how you designed..."
   - "Why did you choose X over Y?"
   - "What would you change if you had to scale this to..."
   - "How do you test..."
   - "What tradeoffs did you make when..."

5. After generating, offer to do a mock interview on any question.
