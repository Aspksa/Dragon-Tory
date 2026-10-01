# Adaptive Reasoning Router 03.00.00

Dragon Tory 00.00.36 automatically chooses reasoning depth. There is no user
button, request parameter or manual Chain/Tree/Hybrid selector.

## Modes

### Chain

Fast linear path for low-complexity tasks with low memory uncertainty and no
relevant contradictions. A simple request can remain a single primary AI call.

### Tree

Used when complexity is high, memory uncertainty is high, or multiple relevant
CONTRADICTS links are present. The tree is bounded to 3–5 compact branches.
Each branch contains only a short approach, evidence for/against, risks and
confidence. It is not a raw hidden chain-of-thought transcript.

### Hybrid

Starts with the normal linear answer. Result Verifier can escalate once to Tree
when score is weak, uncertainty is high, contradictions remain, or several
plausible alternatives survive. The tree result is synthesized and verified
again. There is no recursive escalation loop.

## Routing signals

The local router uses:

- request length and structure;
- response mode;
- number of requested actions;
- analysis/comparison/risk keywords;
- relevant memory uncertainty;
- relevant CONTRADICTS links;
- recent conversation complexity.

Memory signals reuse the already-built MemoryContextPack hits, so routing does
not launch a duplicate semantic recall just to choose reasoning depth.

## Cost controls

- Chain does not build a plan/tree unless existing complexity rules require it.
- Hybrid builds no tree until Verifier crosses escalation thresholds.
- Tree uses one compact branch-generation call, not one full model answer per branch.
- Branch count is capped at five.
- Tree depth metadata is capped at four.
- Hybrid permits at most one tree escalation.

## Safety

Generated plans and trees are wrapped as untrusted derived data and cannot
override system policy. Tree synthesis returns only the final user answer and
is instructed not to expose hidden reasoning. If Tree generation or synthesis
fails, the ordinary chat answer is preserved.

## Observability

The backend records an internal reasoning_route event with mode, complexity,
memory uncertainty, contradiction count and reasons. This is diagnostics only;
the chat API does not expose a manual mode-control field.
