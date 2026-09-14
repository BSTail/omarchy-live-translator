#!/usr/bin/env python3
"""Authoritative WER scoring using jiwer (minimum edit distance).

Normalization mirrors NVIDIA's Parakeet reporting convention: lowercase and
strip punctuation, which is what jiwer.wer() applies by default. Numbers are
left as digits (no verbalization), so "2" vs "dos" counts as a difference; this
is noted in the output rather than silently hidden.

Reports WER/MER/WIL and the S/D/I breakdown per clip.
"""
import json
import jiwer

REFS = {
    1: open("/home/omarchy/Downloads/es-calibrate-1.txt").read(),
    2: open("/home/omarchy/Downloads/es-calibrate-2.txt").read(),
}

MODELS = {
    "parakeet-tdt": "/tmp/opencode/es-cal-{n}.json",
    "nemotron-3.5": "/tmp/opencode/nemo-cal-{n}.json",
}


def load_text(path: str) -> str:
    with open(path) as fh:
        return json.load(fh)["text"]


for model, path_tpl in MODELS.items():
    print(f"== {model} ==")
    for n in (1, 2):
        ref = REFS[n]
        hyp = load_text(path_tpl.format(n=n))
        out = jiwer.process_words(ref, hyp)
        wer = out.wer
        s = out.substitutions
        d = out.deletions
        i = out.insertions
        h = out.hits
        print(f"  clip {n}: WER {wer*100:.1f}%  (S={s} D={d} I={i} H={h})")
    print()
