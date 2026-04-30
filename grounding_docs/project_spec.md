PromptIQ
The one-liner: A real-time Claude Code session coach that detects when your conversation is going off the rails before you've wasted an hour going in circles.

The problem
Every developer using Claude Code has had this experience. You start a session with a clear goal, things seem to be progressing, and 45 minutes later you realize Claude has been confidently building the wrong thing for the last 20 turns. You didn't notice the moment it went wrong. There was no signal.
The problem isn't that Claude failed. The problem is that your session lost coherence at turn 4 and nobody told you. By turn 20 you're so deep in a broken context that starting over is faster than fixing it.
There's no feedback loop. No signal that says "this conversation is drifting" or "Claude is confused because your last three prompts were pulling in different directions." You only find out when the damage is already done.

The product
PromptIQ installs as a Claude Code hook in under 60 seconds:
bash
pip install promptiq
promptiq init
From that point it runs silently in the background during every session. Completely quiet when things are going well. It only speaks up when it detects one of five failure patterns:
1. Context drift -- your prompts have pulled so far from the original task that Claude is effectively starting fresh on each turn, losing the thread of what you were building.
2. Clarification spiral -- Claude has asked clarifying questions two or more times in a row. This almost always means your instructions are ambiguous enough that you're going to get the wrong output.
3. Correction loop -- you've corrected Claude's output three or more times on the same subtask. The underlying instruction is broken, not Claude's execution.
4. Scope explosion -- your prompts are growing in complexity across turns rather than narrowing. This predicts a session that ends with nothing shippable.
5. Context window pressure -- your session is approaching compaction territory and critical context is at risk of being lost before the task completes.
When PromptIQ detects one of these, it fires a single actionable warning directly in your terminal:
⚠️  PromptIQ: Correction loop detected (3 corrections on same subtask)
    Claude may be misunderstanding the core requirement.
    Suggestion: Restate the goal from scratch in one sentence before continuing.
    → Run 'promptiq explain' for full context
One warning. One suggestion. Then silence again.
When the session ends you get a one-page summary: which patterns appeared, at which turns, and what a better prompting strategy would have looked like for the moments that went wrong.

Why this is hard to build
Detecting these five failure patterns sounds simple. It isn't.
Context drift requires maintaining a semantic representation of the original task intent and measuring how far each subsequent prompt has moved from it. That's not keyword matching -- it's continuous embedding comparison across a stateful session object.
Clarification spiral detection requires understanding the difference between Claude asking a question because it needs information versus asking because the prompt was ambiguous. Those look identical on the surface and completely different in the underlying cause.
Correction loop detection requires distinguishing between healthy iterative refinement and broken instruction loops. A user who says "make it slightly darker" three times is refining. A user who says "no that's wrong" three times is stuck.
These distinctions require a LangGraph graph with a stateful session object that accumulates context across every turn, a judge LLM that evaluates pattern emergence rather than individual prompt quality, and a supervisor node that decides when evidence is strong enough to interrupt versus stay silent.
LangSmith traces every detection decision. You can see exactly why PromptIQ fired or stayed silent on any given turn. That observability is what makes the system trustworthy rather than feeling like a random interruption.

The meta-eval framework
How do you know if your failure detector is actually good? You evaluate your evaluator.
You build a ground truth dataset of 50 Claude Code sessions with known outcomes -- sessions that shipped cleanly, sessions that required a full restart, sessions where the user abandoned the task. You measure whether PromptIQ's pattern detection correctly predicted the outcome. That's precision and recall applied to session quality -- the kind of rigorous eval work almost no portfolio projects attempt.
The dataset becomes a public contribution to the Claude Code community. The methodology becomes a LinkedIn post series. The numbers become your interview story.

The architecture
LangGraph manages the stateful session graph: ingestion node, context analysis node, pattern detection node, synthesis node
Claude Code hooks trigger the pipeline automatically after every response via the Stop hook -- no manual commands, no daemon process
MCP connects to the file system to understand what actually changed between turns, grounding pattern detection in real codebase context rather than just conversation text
LangSmith traces every detection decision with full observability
RAGAS measures judge consistency across similar sessions in the meta-eval framework
FastAPI exposes a local endpoint for the session summary and promptiq explain command
Docker containerizes the scoring pipeline for clean local deployment
Zero infrastructure cost. Users bring their own Anthropic API key. No backend, no server, no unexpected bills.

The LinkedIn content flywheel
Post 1: "I analyzed 50 Claude Code sessions that ended in failure. Every single one had one of these 5 patterns. Thread."
Post 2: "The most expensive mistake you make in Claude Code isn't a bad prompt. It's not noticing when a good session turns bad. Here's what that looks like at turn 8."
Post 3: "I built a tool that watches your Claude Code sessions and tells you when you're about to waste an hour. Here's what my own sessions look like after a week of using it."
Post 4: "How do you evaluate an evaluator? The meta-eval problem nobody talks about when building AI tools. Here's my precision and recall numbers."
Post 5: "I open-sourced the failure pattern dataset. 50 labeled Claude Code sessions, 5 failure modes, full methodology. Here's what I found."
Each post is educational, data-driven, and ends with a link to install PromptIQ. The content is inherently novel because nobody has published this data before -- you generate it by building the tool.

The interview moment
You open your terminal. You run a Claude Code session where you deliberately trigger a clarification spiral. PromptIQ fires. You show the LangSmith trace of the detection decision -- specifically the judge LLM reasoning about why two consecutive clarifying questions crossed the threshold. You explain the meta-eval framework and your precision recall numbers on the ground truth dataset.
That's agent reliability, eval infrastructure, and context engineering demonstrated live in 90 seconds on a system you built.

Build timeline at 3 hours per day:
Week 1: Hook registration, transcript parser, JSONL reader, pipeline firing correctly on Stop events
Week 2: Five pattern detectors, LangGraph graph, LangSmith tracing, judge LLM with structured output
Week 3: Meta-eval harness, 50-session ground truth dataset, RAGAS consistency measurement
Week 4: Session summary report, promptiq explain command, README, deploy, first LinkedIn post, launch in r/ClaudeCode and Claude Discord


