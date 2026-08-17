"""
NLLB-200 translation benchmark.

Run inside Docker:
    docker compose exec nllb python benchmark.py

Or locally (requires torch + transformers):
    python benchmark.py

Measures cold-start, tokenization, generation, and end-to-end latency
for representative meeting sentences.
"""
from __future__ import annotations

import os
import time


# Representative meeting sentences (English → Hindi).
SENTENCES = [
    "Good morning everyone.",
    "Can you share your screen?",
    "I think we should move this meeting to tomorrow.",
    "Let's discuss the deployment issue.",
    "What do you think about this approach?",
]

MODEL_NAME = os.environ.get("NLLB_MODEL_NAME", "facebook/nllb-200-distilled-600M")
SOURCE_LANG = "eng_Latn"
TARGET_LANG = "hin_Deva"


def _load_model_and_tokenizer():
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME).to("cpu")
    model.eval()
    load_sec = time.perf_counter() - started
    return model, tokenizer, load_sec


def _bench_sentence(model, tokenizer, text: str, *, num_beams: int, max_length: int) -> dict:
    """Benchmark a single sentence. Returns timing breakdown."""
    # Tokenization
    t0 = time.perf_counter()
    tokenizer.src_lang = SOURCE_LANG
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_length)
    tok_ms = (time.perf_counter() - t0) * 1000

    import torch

    # Warm-up the CUDA allocator if needed (no-op on CPU).
    # Generation
    t1 = time.perf_counter()
    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            forced_bos_token_id=tokenizer.convert_tokens_to_ids(TARGET_LANG),
            max_length=max_length,
            num_beams=num_beams,
            do_sample=False,
        )
    gen_ms = (time.perf_counter() - t1) * 1000

    # Decode
    t2 = time.perf_counter()
    result = tokenizer.decode(outputs[0], skip_special_tokens=True)
    dec_ms = (time.perf_counter() - t2) * 1000

    total_ms = tok_ms + gen_ms + dec_ms
    n_input = inputs["input_ids"].shape[1]
    n_output = outputs.shape[1]

    return {
        "text": text,
        "result": result,
        "input_tokens": n_input,
        "output_tokens": n_output,
        "tokenize_ms": round(tok_ms, 1),
        "generate_ms": round(gen_ms, 1),
        "decode_ms": round(dec_ms, 1),
        "total_ms": round(total_ms, 1),
    }


def run_benchmark(num_beams: int, max_length: int) -> list[dict]:
    """Run the full benchmark suite."""
    model, tokenizer, load_sec = _load_model_and_tokenizer()
    print(f"\nModel loaded in {load_sec:.1f}s  (num_beams={num_beams}, max_length={max_length})")
    print(f"Model: {MODEL_NAME}")
    print(f"Device: cpu")
    print()

    results = []
    # Warm-up with a throwaway inference.
    _bench_sentence(model, tokenizer, "warmup", num_beams=num_beams, max_length=max_length)

    for sentence in SENTENCES:
        r = _bench_sentence(model, tokenizer, sentence, num_beams=num_beams, max_length=max_length)
        results.append(r)
        print(f"  {r['total_ms']:7.1f}ms  ({r['input_tokens']}→{r['output_tokens']} tok)  "
              f"{r['result']}")

    # Summary
    totals = [r["total_ms"] for r in results]
    gens = [r["generate_ms"] for r in results]
    avg = sum(totals) / len(totals)
    p50 = sorted(totals)[len(totals) // 2]
    print(f"\n  Average : {avg:.1f} ms")
    print(f"  P50     : {p50:.1f} ms")
    print(f"  Min     : {min(totals):.1f} ms")
    print(f"  Max     : {max(totals):.1f} ms")
    print(f"  Avg gen : {sum(gens) / len(gens):.1f} ms")
    return results


def main() -> None:
    print("=" * 70)
    print("NLLB-200 Benchmark")
    print("=" * 70)

    # Baseline: current defaults (num_beams=4, max_length=128)
    print("\n--- BASELINE (num_beams=4, max_length=128) ---")
    baseline = run_benchmark(num_beams=4, max_length=128)

    # Optimized: greedy (num_beams=1, max_length=128)
    print("\n--- OPTIMIZED (num_beams=1, max_length=128) ---")
    optimized = run_benchmark(num_beams=1, max_length=128)

    # Aggressive: greedy + tighter max_length
    print("\n--- AGGRESSIVE (num_beams=1, max_length=80) ---")
    aggressive = run_benchmark(num_beams=1, max_length=80)

    # Comparison
    b_avg = sum(r["total_ms"] for r in baseline) / len(baseline)
    o_avg = sum(r["total_ms"] for r in optimized) / len(optimized)
    a_avg = sum(r["total_ms"] for r in aggressive) / len(aggressive)

    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    print(f"  Baseline  (beams=4, max=128): {b_avg:.1f} ms avg")
    print(f"  Optimized (beams=1, max=128): {o_avg:.1f} ms avg  ({(1 - o_avg / b_avg) * 100:.0f}% faster)")
    print(f"  Aggressive(beams=1, max=80) : {a_avg:.1f} ms avg  ({(1 - a_avg / b_avg) * 100:.0f}% faster)")

    # Quality check: print all translations side by side
    print("\n" + "=" * 70)
    print("QUALITY CHECK")
    print("=" * 70)
    for b, o, a in zip(baseline, optimized, aggressive):
        same = "✓" if b["result"] == o["result"] else "✗"
        same2 = "✓" if b["result"] == a["result"] else "✗"
        print(f"  {same} beams4: {b['result']}")
        print(f"    beams1: {o['result']}")
        print(f"    agg   : {a['result']}")
        print()


if __name__ == "__main__":
    main()
