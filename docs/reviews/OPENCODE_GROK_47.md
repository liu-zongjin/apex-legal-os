# OpenCode Go Grok 4.7 verification — 2026-10-17

Scope: additive model registration, Responses transport and local cache refresh.
No database migration or preference rewrite.

Primary references:
- https://docs.opencode.ai/docs/go/ — Grok 4.7 uses `grok-4.7` and the Responses endpoint.
- https://docs.x.ai/developers/rest-api-reference/inference/responses
- https://docs.x.ai/developers/model-capabilities/text/generate-text

Verification:
- Configured Go gateway `/models` returned HTTP 200 and included `grok-4.7`.
- Direct nonstream Responses request with an anonymous “Reply only OK” prompt
  returned HTTP 200, “OK”, and normalized input/output/cache usage.
- Running local `/api/ai-ask-models` included the new model; served home HTML
  referenced frontend version 2026101703.
- Running local `/api/ask-stream`, memory disabled and no history key, replayed
  anonymous color messages and returned “蓝色” via reset/delta/result with
  `model_used=opencode:grok-4.7`. No fallback was used.
- Extended guard: 932 tests passed, syntax/API/architecture/cache checks passed.
- Existing parallel-chat, balance and artifact browser checks passed.
- Anonymous browser fixture exercised AI workspace saved model selection and
  label, API management default model options and visible-model checkbox.

Boundaries: native WKWebView itself was not driven in this pass. Provider-level
connection testing continues to test the provider's existing DeepSeek Flash
probe; the real Grok checks above exercise the new endpoint separately. No live
case files, external legal search or production history writes were exercised.

Recovery: parent commit c7551006c6729e18f318c6b63467824fce303e9f; implementation
branch codex/opencode-grok-47. Frontend version 2026101703; offline shell 260.
