# Gemini Pipeline Optimization — Low-Latency Mass Batch Image Processing

**Branch:** main | **Date:** 2026-04-04
**Design doc:** `ReRoute-V2-Design-Doc.md` | **Eng plan:** `ReRoute-V2-Eng-Plan.md`

---

## Critical Finding: Rate Limits Are Per PROJECT, Not Per Key

**[P1] (confidence: 9/10)**

The design doc assumed round-robin across 10 API keys gives 10x throughput. Wrong. Gemini API rate limits are enforced per GCP project, not per API key. If all 10 keys are from the same project, round-robin gives zero additional throughput. You're still hitting 150-300 RPM (Tier 1) regardless of how many keys you rotate.

**Fix:** Use keys from 5 separate GCP projects. With 5 projects: 750+ RPM effective.

---

## Three-Tier Model Split

| Tier | Model | Use Case | TTFT | Why |
|------|-------|----------|------|-----|
| Detection | Gemini 2.5 Flash-Lite | Frame batch analysis ("what items?") | 0.29s | Fast, cheap, classification-grade |
| Detail | Gemini 2.5 Flash | Per-item title/description/category/pricing | 0.50s | Smarter, still fast |
| Browser agents | ChatBrowserUse | Browser-Use agent LLM | — | Optimized for browser tasks, separate rate limits |

This replaces the original single-model approach (Gemini for everything).

---

## Context Caching (90% Cost Reduction)

Gemini 2.5 supports implicit context caching at >=1,024 tokens on Flash-Lite. The system prompt for item detection is identical every call.

**Implementation:**
- Pad system prompt to >=1,024 tokens (add output format examples, edge cases, item examples)
- Implicit caching activates automatically after first call
- 90% discount on all subsequent calls
- Likely faster TTFT since prompt is pre-processed

```python
ANALYSIS_PROMPT = """
You are analyzing video frames of items someone wants to sell.
For each distinct item visible:
- name: product name with model/specs (e.g., "iPhone 15 Pro 256GB Space Black")
- category: electronics | clothing | accessories | home | other
- condition: new | like_new | good | fair | poor
- frame_indices: which frames show this item (list of ints)
- bounding_box: [x1, y1, x2, y2] normalized 0-1 for best frame
- confidence: 0.0-1.0

Return JSON array. Multiple items per batch is normal.
If no items visible (hand motion, blur, transition), return [].
[... pad with examples to exceed 1024 tokens ...]
"""
```

---

## Parallel Fan-Out Architecture

```
VIDEO INPUT (30s video)
    |
    v
ffmpeg (streaming pipe, 1 fps)
    |
    v
Frame buffer: collect 3-5 frames per batch
    |
    +-- Batch 1 (frames 0-4)  --> GCP Project A (Flash-Lite, Priority tier)
    +-- Batch 2 (frames 5-9)  --> GCP Project B (parallel)
    +-- Batch 3 (frames 10-14) --> GCP Project C (parallel)
    +-- Batch 4 (frames 15-19) --> GCP Project D (parallel)
    +-- Batch 5 (frames 20-24) --> GCP Project E (parallel)
    +-- Batch 6 (frames 25-29) --> GCP Project A (round-robin)
    |
    v (asyncio.as_completed -- yield items from whichever batch finishes first)
    |
    v
ItemCards emitted --> orchestrator spawns agents immediately
```

**Key implementation pattern:**
```python
async def streaming_analysis(video_path: str):
    """Extract frames, batch them, fire to Gemini in parallel, yield items."""
    frame_buffer = []
    batch_tasks = []

    async for frame in extract_frames_streaming(video_path, fps=1):
        frame_buffer.append(frame)

        if len(frame_buffer) >= BATCH_SIZE:  # 3-5 frames
            task = asyncio.create_task(
                analyze_batch(frame_buffer.copy(), project_key=next_key())
            )
            batch_tasks.append(task)
            frame_buffer.clear()

    if frame_buffer:
        batch_tasks.append(asyncio.create_task(
            analyze_batch(frame_buffer, project_key=next_key())
        ))

    for coro in asyncio.as_completed(batch_tasks):
        result = await coro
        if result and not isinstance(result, Exception):
            for item in result:
                yield item  # orchestrator spawns agent immediately
```

---

## Priority Inference Tier

Google's Priority vs Flex inference tiers:
- **Priority**: guaranteed resource allocation, lower latency. Use for frame analysis (user-facing).
- **Flex**: cheaper, no SLA. Use for route decision, detail generation (non-urgent).

---

## Optimized Latency Breakdown

```
BEFORE (v1):                     AFTER (optimized v2):
Video upload --------- 5s        Video upload ---------- 5s
Frame extraction ----- 8s        ffmpeg streaming ------ 0.5s
  (wait for all)                 Frames 0-4 ready ------ 2.5s
Gemini analysis ------ 4s          -> Batch 1 -> Project A (Flash-Lite)
  (wait for all items)           Frames 5-9 ready ------ 5.0s
Agent dispatch ------- 0.1s        -> Batch 2 -> Project B (parallel)
Route bidding -------- 6s        Batch 1 returns ------- ~4.0s
                                   * FIRST ITEM -> agent spawns
Total wait: ~23s                 All batches complete --- ~10s

                                 First agent working: ~9-10s
                                 (clear opening shot: ~7-8s)
                                 All agents working: ~15s
```

---

## Step 0 Benchmark Additions

Before building, validate:
1. Multi-project Gemini key setup (confirm rate limits are per-project)
2. Flash-Lite vs Flash latency for frame analysis (5 calls each, compare TTFT)
3. Context caching activation (system prompt >=1,024 tokens, verify cached reads)
4. Priority vs Flex tier latency difference

---

## Gemini Error Handling

- If a batch call fails or times out: retry once with 2s delay using a DIFFERENT project key
- If retry fails: skip that frame batch, continue pipeline
- If Gemini returns no items from a batch: normal (not every frame shows an item), continue
- Log failures but never block the pipeline

---

## Docs Updated

| File | What changed |
|------|-------------|
| `ReRoute-V2-Design-Doc.md:183` | Backend stack: three-tier model split, context caching, multi-project keys, Priority inference |
| `ReRoute-V2-Design-Doc.md:265-283` | Latency diagram: parallel fan-out numbers |
| `ReRoute-V2-Design-Doc.md:329` | Open Question #4: resolved with three-tier split |
| `ReRoute-V2-Eng-Plan.md` Decision #2 | Flash-Lite + Flash + ChatBrowserUse split |
| `ReRoute-V2-Eng-Plan.md` Step 0 | Added key verification, Flash-Lite TTFT test, caching test |
| `ReRoute-V2-Eng-Plan.md` Step 4 | Updated latency targets |
| `TEAM-EXECUTION-PLAN.md` Person 3 intake.py | Parallel batch fan-out, model selection, multi-project keys |

---

## Sources

- Gemini API Rate Limits: https://ai.google.dev/gemini-api/docs/rate-limits
- Context Caching: https://ai.google.dev/gemini-api/docs/caching
- Gemini 2.5 Flash Performance: https://artificialanalysis.ai/models/gemini-2-5-flash
- Flex and Priority Inference: https://blog.google/innovation-and-ai/technology/developers-tools/introducing-flex-and-priority-inference/
- Video Understanding: https://ai.google.dev/gemini-api/docs/video-understanding
