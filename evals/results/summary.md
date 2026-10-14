# Agent evaluation

| Metric | v1 (groq / openai/gpt-oss-120b) | v2 (groq / openai/gpt-oss-120b) |
|---|---|---|
| cases | 102.0 | 102.0 |
| success_rate | 78% | 35% |
| tool_selection_accuracy | 87% | 39% |
| check_accuracy | 89% | 95% |
| error_rate | 0% | 57% |
| mean_latency_seconds | 2.5 | 3.6 |
| p95_latency_seconds | 4.4 | 18.9 |
| mean_model_calls | 2.2 | 1.0 |
| mean_tokens | 3183.4 | 1513.5 |

## v1 by category

| Category | Cases | Success | Tool selection | Checks |
|---|---|---|---|---|
| ambiguous | 9 | 100% | 100% | 100% |
| create | 20 | 80% | 100% | 94% |
| delete | 8 | 75% | 75% | 73% |
| plan_day | 8 | 100% | 100% | 100% |
| priority | 5 | 100% | 100% | 100% |
| project | 10 | 90% | 90% | 90% |
| query | 12 | 100% | 100% | 100% |
| robust | 10 | 60% | 70% | 85% |
| start | 8 | 62% | 100% | 84% |
| update | 12 | 33% | 42% | 78% |

## v2 by category

| Category | Cases | Success | Tool selection | Checks |
|---|---|---|---|---|
| ambiguous | 9 | 11% | 11% | 100% |
| create | 20 | 75% | 85% | 97% |
| delete | 8 | 0% | 0% | 100% |
| plan_day | 8 | 0% | 0% | 100% |
| priority | 5 | 0% | 0% | 100% |
| project | 10 | 0% | 0% | 0% |
| query | 12 | 100% | 100% | 100% |
| robust | 10 | 0% | 0% | 100% |
| start | 8 | 75% | 100% | 90% |
| update | 12 | 17% | 17% | 100% |
