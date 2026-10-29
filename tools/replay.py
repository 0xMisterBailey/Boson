#!/usr/bin/env python3
"""Owner-only replay (SPEC v3 §4.2, operator 1a + 2a): one T12 round replayed on branch owner-only.

usage: replay.py NN    (ComfyUI with Klein on COMFY, the open critic on CRITIC_PORT, studio repo on owner-only)
  1. the round in-graph: Draft Brief on the branch (writer, committed) -> Klein plates -> Verdict stops
  2. the open critic's drift read -> history/round-NN/OPEN-READ.md, committed
  3. the owner's stored T12 sentence for round NN (from main, tag rNN) committed as the verdict
  4. Digest (writer); then it stops: the operator approves the proposed rules live (2a)
"""
import os, pathlib, re, subprocess, sys, time

BOSON = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BOSON / "tools"), str(BOSON / "boson")]
import grid as gr, open_read, render_plates as rp, studio as st  # noqa: E402

BUNDLE = str(BOSON / "tests" / "fixtures" / "poc" / "ex-libris.bundle")
BRANCH = "owner-only"


def owner_sentence(nn):
    """The owner's T12 words on round nn, as the main line's grid prints them (no paraphrase)."""
    line = gr.verdict_line(st.load(BUNDLE, f"r{nn}"))
    return re.search(r'"([^"]+)"', line).group(1)


def main(nn):
    t0 = time.time()
    lap = lambda what: print(f"[{(time.time() - t0) / 60:.1f} min] {what}", flush=True)  # noqa: E731
    said = owner_sentence(nn)
    lap(f"round {nn}: owner's stored sentence: {said!r}")
    s = st.load(BUNDLE, BRANCH)
    assert st.next_round(s) == nn, f"branch is at round {st.next_round(s)}, not {nn}"
    plates = rp.round_(BUNDLE, BRANCH, BOSON / "tests" / "fixtures" / "poc" / "ex-libris-plates")
    lap("drafted + rendered")
    s = st.load(BUNDLE, BRANCH)
    repo, branch = st.writable(s)
    open_read.read(repo, nn, plates, os.environ.get("CRITIC_PORT", "8099"))
    s = st.commit(repo, branch, [pathlib.Path("history") / f"round-{nn}" / "OPEN-READ.md"],
                  f"round {nn}: open read (Qwen3.8, local)")
    lap("open read committed")
    s = st.commit_verdict(s, nn, said)
    s, meta = st.digest(s)
    lap(f"digested by {meta['writer']} (${meta['cost_usd']})")
    rid, props = st.proposed(s)
    print(f"\nround {rid} proposes (operator approves: '{rid}: 1,3' or '{rid}: none'):")
    for k, r in props.items():
        print(f"  {k}. {r}")


if __name__ == "__main__":
    main(sys.argv[1])
