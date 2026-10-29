#!/usr/bin/env python3
"""Blind shuffle deck (SPEC v3 §4.3, 10-22): 4 pairs, a round-01 plate vs a round-02 plate of the same seed,
sides shuffled. Pass = the operator picks the round-02 side (the studio with more of their verdicts behind
it) in >= 3 of 4. Fixed before the run: series pairs and sides come from RNG seed 1022, arm orig.

usage: blind_shuffle.py build   -> notes/blind-shuffle-1022/deck.json (+ plates/), key in notes/blind-shuffle-1022.key.json
       blind_shuffle.py score   -> reads deck.labels.jsonl, prints k/4 and PASS/FAIL
"""
import json, pathlib, random, shutil, sys

BOSON = pathlib.Path(__file__).resolve().parents[1]
PLATES = BOSON / "tests" / "fixtures" / "poc" / "ex-libris-plates"
OUT = BOSON / "notes" / "blind-shuffle-1022"
KEY = OUT.parent / "blind-shuffle-1022.key.json"  # outside the deck folder: the engine serves that folder


def build():
    man = [json.loads(l) for l in (PLATES / "manifest.jsonl").read_text().splitlines() if l.strip()]
    orig = [m for m in man if m.get("prompt_arm", "orig") == "orig"]
    rng = random.Random(1022)
    cards, key = [], {}
    for k, seed in enumerate([901201, 901201, 901202, 901202], 1):
        a = rng.choice([m for m in orig if m["round"] == "r01" and m["seed"] == seed])
        b = rng.choice([m for m in orig if m["round"] == "r02" and m["seed"] == seed])
        orig = [m for m in orig if m not in (a, b)]  # no plate twice
        later_right = rng.random() < 0.5
        left, right = (a, b) if later_right else (b, a)
        cid = f"pair{k}"
        for side, m in (("L", left), ("R", right)):
            (OUT / "plates").mkdir(parents=True, exist_ok=True)
            shutil.copy(PLATES / m["file"], OUT / "plates" / f"{cid}{side}.png")
        img = lambda s: f'<img src="/media/plates/{cid}{s}.png" style="width:100%">'  # noqa: E731
        cards.append({"id": cid, "left": img("L"), "right": img("R"), "left_label": "left", "right_label": "right"})
        key[cid] = {"later": "right" if later_right else "left", "left": left["spec"], "right": right["spec"]}
    deck = {"config": {"title": "WHICH STUDIO?", "round_size": 4,
                       "question": "Which plate comes from the studio with more of your verdicts behind it?",
                       "yes": {"label": "RIGHT ▶"}, "no": {"label": "◀ LEFT"}, "tags": [],
                       "footnote": "First read. Same seed in each pair; one is round 01, one is round 02.",
                       "done_message": "Done: 4 pairs. Tell the agent 'score the shuffle'."},
            "cards": cards}
    (OUT / "deck.json").write_text(json.dumps(deck, indent=1) + "\n")
    KEY.write_text(json.dumps(key, indent=1) + "\n")
    print(OUT / "deck.json")


def score():
    labels = {}
    for line in (OUT / "deck.labels.jsonl").read_text().splitlines():
        r = json.loads(line)
        labels.pop(r["id"], None) if r.get("op") == "undo" else labels.__setitem__(r["id"], r) if "label" in r else None
    key = json.loads(KEY.read_text())
    hits = sum(1 for c, v in key.items() if labels.get(c, {}).get("label") == (1 if v["later"] == "right" else 0))
    print(f"{hits}/4 picked the round-02 side ({len(labels)} answered): {'PASS' if hits >= 3 else 'FAIL'}")


if __name__ == "__main__":
    {"build": build, "score": score}.get((sys.argv[1:] or [""])[0], lambda: sys.exit(__doc__))()
