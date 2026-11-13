---
name: eval
description: Design or run evals for AI-generated output using RAGAS metrics
---

# /eval

Design or run evaluations for PrepAgent's AI outputs.

## Steps

### If designing a new eval:

1. Ask what output is being evaluated (research summaries, interview questions, company analysis, etc.).
2. Define the golden eval set:

```markdown
# Eval: [Output Type]

## Golden set
| Input | Expected output (or key facts) | Source |
|-------|-------------------------------|--------|
| [test input 1] | [expected result] | [ground truth source] |
| [test input 2] | [expected result] | [ground truth source] |

## Metrics
- **Faithfulness:** Does the output contain only facts from the retrieved context? (0-1)
- **Answer relevance:** Does the output address the input question? (0-1)
- **Context precision:** Is retrieved context relevant to the question? (0-1)
- **Context recall:** Does retrieved context cover the expected output? (0-1)

## Pass thresholds
- Faithfulness >= 0.85
- Answer relevance >= 0.80
- Context precision >= 0.75
- Context recall >= 0.75

## LLM-as-judge prompt (for open-ended output)
```
Given this input: {input}
And this output: {output}
Rate on a 1-5 scale:
- Accuracy: Are all facts correct?
- Completeness: Are key points covered?
- Usefulness: Would this help someone prepare for an interview?
Respond with JSON: {"accuracy": N, "completeness": N, "usefulness": N, "reasoning": "..."}
```
```

3. Save to `tests/evals/[output-type]-eval.md`.

### If running an existing eval:

1. Read the eval definition from `tests/evals/`.
2. Run each golden set input through the pipeline.
3. Score using the defined metrics.
4. Output results as a table with pass/fail per metric.
5. Flag any metric below threshold.
