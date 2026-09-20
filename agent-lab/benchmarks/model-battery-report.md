# Local model battery — 2026-09-19

## Test conditions

Hardware supplied for the test: Intel Core i5-8400, 32 GB DDR4, and a GTX 1070 with 8 GB VRAM. Both models ran through the local Vulkan `llama-server` with an 8192-token context.

- **Gemma 4 E4B Q4_0:** reasoning on, 1024-token reasoning budget, temperature 0.6, top-p 0.95.
- **Qwen3 8B Q4_K_M:** `/no_think`, temperature 0.7, top-p 0.8.

The comparison is therefore between the two profiles actually usable in Agent Lab, not an abstract model-vs-model benchmark.

## Results

| Probe | Gemma | Qwen |
|---|---|---|
| Personality | Correct, formal, somewhat generic | Correct, more conversational and better scoped |
| Exact JSON formatting | Pass | Pass |
| Three-box logic puzzle | Correct after a 2048-token rerun | Incorrect relabeling |
| Python deduplication | Correct, with complexity and examples | Correct, concise |
| JavaScript debugging | Correct after a 2048-token rerun | Incorrect: returns the first truthy item, not the last |
| Hardware honesty | Correct after a 2048-token rerun | Incorrect CPU generation/core-count claim |
| Ambiguous backup request | Usable, but more presumptive | Usable and concise |
| Summarization | Good, verbose | Good, concise |
| Cross-turn memory | Recalled `CEDAR-47` and the benchmark caveat | Recalled `CEDAR-47` and the benchmark caveat |
| Structured tool loop | Listed, wrote, read, and finished successfully | Listed, wrote, read, and finished successfully |

The first Gemma pass used a 700-token API limit and hit the length ceiling on the harder reasoning prompts. Those prompts were rerun at 2048 tokens; the visible answers were then complete and correct. This is a configuration requirement, not a cosmetic detail: Gemma's thinking consumes the same response budget.

## Measured performance

Across the nine matched primary probes:

| Measure | Gemma | Qwen |
|---|---:|---:|
| Startup | 16.63 s | 19.15 s |
| Average response | 9.83 s | 4.28 s |
| Total response time | 88.50 s | 38.49 s |
| GPU memory after load | 3,982 MiB | 6,598 MiB |
| Free GPU memory after load | 4,086 MiB | 1,470 MiB |

The structured tool test took 20.1 seconds with Gemma and 14.2 seconds with Qwen. Both completed the exact task in four model turns and three tool calls.

## Verdict

**Gemma is the more viable default for this machine.** It is slower, but it has substantially more VRAM headroom and was materially more reliable on reasoning, debugging, and factual self-restraint. Qwen is viable as a fast mode for low-risk chat, summaries, and simple transformations; it is not yet trustworthy as the default coding or agent model in no-think mode.

The practical setup is Gemma for agent work and Qwen when latency matters more than verification. Keep Gemma's response budget around 2048 tokens when reasoning is enabled. A fair next experiment would be Qwen with thinking enabled, but that is a different operating point from the one tested here.

Source data: `model-battery-20260919.json`; tool-loop runs are under `agent-lab/runs/`.
