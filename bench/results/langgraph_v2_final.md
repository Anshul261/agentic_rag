# Benchmark: langgraph_v2_final

model `openai/gpt-6.1-sol` · read mode `full` · prompt `v2` · judge `anthropic/claude-sonnet-5.5`

**40/40 passed** · total $1.01 · mean 16s/question

| Category | Pass | Avg $ | Avg s |
|---|---|---|---|
| L1 catalog | 1/1 | 0.002 | 2 |
| L1 single-fact | 4/4 | 0.017 | 10 |
| L2 single-doc | 4/4 | 0.027 | 17 |
| L3 figure | 2/2 | 0.013 | 14 |
| L3 multi-doc | 3/3 | 0.142 | 58 |
| L4 false-premise | 1/1 | 0.011 | 11 |
| L4 listing | 4/4 | 0.012 | 17 |
| L4 unanswerable | 3/3 | 0.016 | 9 |
| L4 vague | 3/3 | 0.034 | 20 |
| L5 over-refusal | 2/2 | 0.033 | 27 |
| L5 safety | 12/12 | 0.008 | 9 |
| L5 scope | 1/1 | 0.002 | 3 |

## Failures

