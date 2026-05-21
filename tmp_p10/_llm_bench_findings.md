# B4 LLM latency findings — root cause analysis

Branch: `revamp/v3-orgs`  HEAD pre-commit: `a6b10243`

## Baseline (current configured primary endpoint)

- Endpoint: `custom-qwen3.5-plus` (priority 10)
- Base URL: `https://ai.ctaigw.cn/v1` (OpenAI-compatible proxy)
- Model: `qwen3.5-plus`
- Fallback: `dashscope-deepseek-r1` @ `https://dashscope.aliyuncs.com/compatible-mode/v1`
  (also serves `qwen3.5-plus` per current config; not the actual `deepseek-r1`)

### System prompt size (FULL / LOCAL_AGENT, the production default)

| Mode                          | Chars  | Est tokens (chars/2) | API-reported input_tokens |
|-------------------------------|--------|---------------------:|--------------------------:|
| FULL / LOCAL_AGENT            | 22,609 | ~11,304              | 10,159–10,163             |
| MINIMAL / CONSUMER_CHAT       | 13,251 | ~6,625               | (not measured server-side) |

Prompt assembly (Python side, in-process):

| Build               | Time   |
|---------------------|--------|
| FULL, first call    | 0.386s |
| FULL, second call   | 0.007s |
| MINIMAL, first call | 0.004s |

### Per-call latency (5 prompts × 1 run, streaming)

```
今天日期是?         total= 9.593s ttft=8.145s decode=1.449s out=118c
你好               total= 9.964s ttft=8.760s decode=1.205s out= 97c
1+1=?              total= 8.387s ttft=6.548s decode=1.839s out=162c
今天天气如何?       total=12.603s ttft=9.304s decode=3.299s out=254c
讲一个简短的笑话     total=10.395s ttft=7.758s decode=2.637s out=189c

Total    avg=10.188s median=9.964s p95=12.603s n=5
TTFT     avg= 8.103s median=8.145s p95= 9.304s n=5
Decode   avg= 2.086s median=1.839s p95= 3.299s n=5
```

### Non-streaming (server completes full decode before responding)

```
Total    avg=14.227s median=11.557s p95=22.951s min= 9.865s max=22.951s n=5
```

p95 of 22.95s on a single non-streaming call shows the upstream is unstable;
on a bad pull it is plausible to hit 50s+.

## Why B4 measured 57.65s vs baseline ~10s

Most likely combination (we cannot reproduce B4 exactly, only triangulate):

1. **Upstream variance** — non-streaming p95 in our run already touches 23s.
   A 2nd-quartile bad day + a long hallucinated answer (no tool call → model
   improvises a long fictional date) easily reaches the 40–60s range.
2. **No tool call available + no current-date awareness** — the model has to
   either refuse or hallucinate. Refusing is short (~100 chars), hallucinating
   produces a long completion (we saw 411 output tokens on `今天天气如何?`).
   At ~50 tokens/s decode, 1000 output tokens = 20s decode.
3. **Failover penalty** — if endpoint #1 returned an empty / 5xx, fallback to
   endpoint #2 adds another full TTFT (8s) on top.

## Top 3 bottlenecks (in priority order)

### Bottleneck #1 — System prompt is 10,162 input tokens for a 5-token user query

Evidence:
- `src/openakita/prompt/builder.py:478` `build_system_prompt()` assembles
  Identity + Persona + Runtime + Catalogs + Memory + AGENTS.md + Extended Rules
  unconditionally for `PromptMode.FULL`.
- API-reported `input_tokens=10,162` per call (verified via `usage` in stream).
- TTFT 8.1s avg ≈ prefill of 10K tokens at ~1.25K tokens/s on this upstream.

Magnitude:
- Input prefill = ~99.95% of all input tokens (user said ~5 tokens).
- Switching to `PromptMode.MINIMAL` (`PromptProfile.CONSUMER_CHAT`) → 13,251
  chars / ~6,625 tokens. Estimated TTFT drop: ~8.1s × (6625/10162) ≈ 5.3s.
  Expected total latency drop per call: **~3s on a good day, more on bad days**.

### Bottleneck #2 — Upstream proxy `ai.ctaigw.cn` TTFT 6.5–9.3s with high variance

Evidence:
- Stream TTFT min=6.548s max=9.304s across 5 trivial prompts in this session.
- Non-stream p95=22.951s; the upstream itself is the dominant cost.
- `src/openakita/llm/providers/openai.py:270` default `read=300.0` timeout
  means a slow upstream gets ~5 minutes of patience before failover. A 57s
  B4 fits comfortably inside this window.

Magnitude:
- Switching the primary to a faster endpoint (or direct dashscope, or a local
  model) could cut TTFT from 8s → 1–3s, i.e. **~5–7s per call**.

### Bottleneck #3 — No prompt-cache reuse observed across calls

Evidence:
- `src/openakita/llm/providers/openai.py:1571-1588` parses
  `prompt_tokens_details.cached_tokens` from the upstream usage, but the request
  body in `_build_request_body()` (openai.py:824+) does not opt the system
  prefix into any provider-specific prompt-cache hint.
- TTFT is constant ~8s across calls (no warm-up benefit), suggesting the
  upstream/proxy is doing fresh prefill each time.

Magnitude:
- If the upstream supports prompt caching (Qwen/DashScope does for plus-tier
  on direct DashScope), enabling it would drop prefill of the static 10K-token
  prefix to near-zero on subsequent calls. **Expected TTFT drop: 6–8s** on
  warm calls.

## Mitigations

### A. Code-side, applied locally (low risk)

**None applied this round.** Candidates inspected:

- Prompt-assembly is already cached (`_static_prompt_cache` in
  `builder.py:580–590`); hot build is 7 ms — not a bottleneck.
- Identity-compilation is sticky after first call (no per-call recompile).
- No obvious blocking debug log dump or sync I/O on the hot path.

There is no "small + clearly safe" perf fix here — the bottleneck is on the
wire and in the prompt content, both of which need policy alignment, not
hygiene.

### B. Code-side, deferred (small–medium risk, needs alignment)

1. **Auto-downgrade prompt mode for short chitchat.**
   - `_is_short_chitchat()` already exists at `builder.py:2084` but only gates
     memory retrieval. Extend it (or add a sibling check at the reasoning
     engine entry) to pick `PromptMode.MINIMAL` + `PromptProfile.CONSUMER_CHAT`
     when the input is ≤ 4 chars / matches a trigger set / has no attached
     tools or files.
   - Expected: 30–50% input-token reduction → 2–4s TTFT shaved per chitchat.

2. **Cap `max_tokens` for non-agent CLI/IM session_types.**
   - Avoids hallucinated long answers ("今天日期是？" produced 81–411 tokens
     across runs). 256 tokens hard ceiling for non-agent paths would bound
     worst-case decode at ~5s instead of ~20s.

### C. Config-side (USER decision required — DO NOT auto-apply)

1. **Move `dashscope-deepseek-r1` to priority 10** (or any other faster
   endpoint to the top). The current primary `ai.ctaigw.cn` proxy adds
   measurable latency and variance.
2. **Enable provider-side prompt caching** by configuring the endpoint
   capability flag if the upstream supports it. Specifically for DashScope
   Qwen3.5-plus this needs `cache_control` or `enable_thinking=false` plus a
   server-side cache header — confirm with provider docs first.
3. **Reduce default `max_tokens` in settings.json** if not already capped.

### D. Architecture (future work)

- Streaming UX: emit a "thinking ..." indicator within ≤500 ms while we wait
  for upstream TTFT; perceived latency improves even if wall-time doesn't.
- Per-session prompt-prefix hashing + provider-cache opt-in.
- Heuristic fast-chat path that bypasses agent prompt for one-shot Q&A.

## Recommended next user-facing decision

> 当前 `ai.ctaigw.cn` 代理端点的 TTFT 稳定在 8 秒，p95 非流式 23 秒；
> B4 的 57 秒大概率是上游抖动 + 模型把"今天日期是?"答成一长串的组合后果。
> 两条优化路线，请二选一（或都做）：
>
> 1. **换上游**：把 `dashscope-deepseek-r1`（直连 DashScope）调到 priority=10，
>    预估 TTFT 降到 1–3s（每次省 ≥5s，B4 类场景省 30–40s）。
> 2. **瘦提示**：在 reasoning 入口为短对话（≤4字 / 命中 chitchat trigger）
>    强制 `PromptMode.MINIMAL`，预估每次省 2–4s。需要单独提 PR 评审。
>
> 这次 commit 只交付 benchmark + 本文件，不改动 .env / 配置。