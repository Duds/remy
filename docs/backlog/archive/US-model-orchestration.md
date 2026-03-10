# ✅ Done

# User Story: Multi-Model Orchestration

## Summary

As a user, I want Remy to intelligently route my requests to the most appropriate AI model (Claude, Mistral, or Moonshot) to optimize for speed, cost, and reasoning capability, ensuring a snappy Telegram experience.

---

## Background

Currently, Remy primarily uses Claude with a local Ollama fallback. To improve flexibility and cost-efficiency, we want to implement the strategy outlined in `docs/model_orchestration_refactor.md`. This involves adding support for Mistral and Moonshot AI and refining the routing logic based on task type and context length.

---

## Acceptance Criteria

1. **Multi-Model Support:** Integration with Mistral and Moonshot AI APIs.
2. **Intent-Based Routing:** The orchestrator identifies the task type (e.g., summarization, reasoning, coding) and selects the optimal model according to the mapping in `model_orchestration_refactor.md`.
3. **Context-Aware Scaling:** Automatic escalation to larger context models when input exceeds thresholds (e.g., 50k, 128k tokens).
4. **Dynamic Fallback:** Graceful fallback to secondary models if the primary choice is unavailable or fails.
5. **Telegram Responsiveness:** Low-latency models (Haiku, Mistral Medium) are prioritized for interactive messages.
6. **Cost Optimization:** Preference for the "cheapest capable model" for every task.

---

## Implementation

- **New Clients:** `remy/ai/mistral_client.py` and `remy/ai/moonshot_client.py`.
- **Enhanced Router:** Update `remy/ai/router.py` to implement the new routing table and logic.
- **Config Updates:** Add API keys and model names for Mistral and Moonshot to `remy/config.py`.
- **Classification:** Update `remy/ai/classifier.py` if needed to better distinguish between the new task categories.

---

## Test Cases

| Scenario                                    | Expected Model                      |
| ------------------------------------------- | ----------------------------------- |
| Simple greeting                             | Claude Haiku or Mistral Medium      |
| Summarizing a 100kb file                    | Claude Sonnet or Mistral Large      |
| Complex coding request                      | Moonshot K2 Thinking or Claude Opus |
| Safety-critical action (e.g., system write) | Claude Sonnet (with validation)     |
| Claude API down                             | Fallback to Mistral or Ollama       |

---

## Out of Scope

- Real-time model performance benchmarking (A/B testing).
- Support for models beyond Claude, Mistral, and Moonshot in this phase.
