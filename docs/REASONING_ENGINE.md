# Cognitive Core IV — Reasoning Engine

Version **00.00.32** adds three cooperating layers to Dragon Tory chat.

## Reasoning Planner

The planner runs only for complex requests. It produces a bounded JSON plan with:

- objective;
- known facts;
- missing information;
- execution steps;
- success criteria;
- risks;
- confidence.

Short small-talk messages do not invoke the planner.

## Result Verifier

After the main answer, the verifier compares the result with:

- the original task;
- the execution plan;
- the available memory/document context.

It returns a pass/fail decision, verification score, issues, unmet criteria and
contradictions. When a fix is possible, it may return a complete revised answer.

If verification is unavailable, the original answer is preserved and no
experience rule is learned from that run.

## Experience Learning

A verified task/result episode receives the tag `verified-outcome` only when
verification passed and the score meets the learning threshold.

A reusable rule can be proposed only after at least three similar verified
episodes. The rule is stored as an INSTRUCTION candidate with the
`experience-rule` tag and is sent through Memory Guardian.

Because INSTRUCTION is high-impact memory, the candidate is not silently
promoted into a permanent rule without Guardian review.

## Safety and prompt boundaries

Memory, documents and generated plans remain subordinate to system policy.
Untrusted document content is never allowed to become a system instruction.
Planner or verifier failure must not break ordinary chat.
