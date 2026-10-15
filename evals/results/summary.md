# Agent evaluation

| Metric | v1 (groq / openai/gpt-oss-120b) | v2 (groq / openai/gpt-oss-120b) | v3-gemini (gemini / gemini-3.1-flash-lite) | v4-preview (gemini / gemini-3.1-flash-lite) |
|---|---|---|---|---|
| cases | 102.0 | 102.0 | 102.0 | 14.0 |
| success_rate | 78% | 84% | 96% | 100% |
| tool_selection_accuracy | 87% | 88% | 97% | 100% |
| check_accuracy | 89% | 94% | 98% | 100% |
| error_rate | 0% | 0% | 0% | 0% |
| mean_latency_seconds | 2.5 | 2.6 | 4.8 | 3.7 |
| p95_latency_seconds | 4.4 | 4.1 | 20.5 | 6.4 |
| mean_model_calls | 2.2 | 2.4 | 2.3 | 2.6 |
| mean_tokens | 3183.4 | 3768.5 | 4871.4 | 10185.8 |

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
| ambiguous | 9 | 100% | 100% | 100% |
| create | 20 | 75% | 85% | 97% |
| delete | 8 | 88% | 88% | 86% |
| plan_day | 8 | 100% | 100% | 100% |
| priority | 5 | 100% | 100% | 100% |
| project | 10 | 80% | 80% | 80% |
| query | 12 | 100% | 100% | 100% |
| robust | 10 | 60% | 60% | 89% |
| start | 8 | 75% | 100% | 90% |
| update | 12 | 83% | 83% | 95% |

## v3-gemini by category

| Category | Cases | Success | Tool selection | Checks |
|---|---|---|---|---|
| ambiguous | 9 | 100% | 100% | 100% |
| create | 20 | 100% | 100% | 100% |
| delete | 8 | 88% | 88% | 86% |
| plan_day | 8 | 100% | 100% | 100% |
| priority | 5 | 100% | 100% | 100% |
| project | 10 | 100% | 100% | 100% |
| query | 12 | 100% | 100% | 100% |
| robust | 10 | 100% | 100% | 100% |
| start | 8 | 88% | 88% | 100% |
| update | 12 | 83% | 92% | 95% |

## v4-preview by category

| Category | Cases | Success | Tool selection | Checks |
|---|---|---|---|---|
| alerts | 2 | 100% | 100% | 100% |
| memory | 2 | 100% | 100% | 100% |
| notes | 4 | 100% | 100% | 100% |
| project | 1 | 100% | 100% | 100% |
| report | 2 | 100% | 100% | 100% |
| reschedule | 3 | 100% | 100% | 100% |
