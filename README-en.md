# Jian / 竹简

**A local, verifiable memory kernel and persona layer for long-lived AI companions.**

> Persona does not live in the model weights. It lives in a recomputable artifact plus a set of verifiable tests.

[中文 README](README.md) · [Paper (Chinese)](docs/PAPER.md) · [Paper (English)](docs/PAPER-en.md)

---

## What it answers

| Question | Mechanism | Measured |
|---|---|---|
| Has this memory been tampered with? | append-only chain + hash chain | one changed byte is caught; `jian-kernel compile` verifies the chain by default (`E_KN_TAMPER`) |
| Can it move to another device? | one capsule file, persona recomputed on arrival | identical `kid` on device B |
| Is it still the same person after a model swap? | content identity `kid` + behavioral identity PCS | PCS = 0.649 (95% CI [0.522, 0.754]); PCS is an **evaluation result**, not carried in the capsule |
| Does context get expensive? | budgeted assembly (4k cap) | 200k memories, p50 13 ms |
| Can Chinese be parsed without a model? | rule layer (kinship / timex / slang) | holdout 14/14 |

## Run it

```bash
python -m unittest discover -s tests -v     # 339 tests
```

Zero third-party dependencies, Python 3.11+. The core libraries never touch the network and never call a model; network and model calls live only in `tools/`.

## Layout

```
jian/             evidence layer: store, hash chain, byte reproducibility, payload blobs
jian_cn/          Chinese rule layer: kinship, relative time, slang decay, script folding
jian_recall/      retrieval and budgeted assembly: FTS5 + bigrams + 4k cap
jian_kernel/      persona kernel: deterministic compile, gates, history, proposals
jian_pcs/         behavioral identity: PCS, executable rules, collapse depth
jian_projection/  projection layer: trace contract and per-form projectors (M11+)
tools/            external adapters (the only place with network): proposer, reply capture, matrix runs
experiments/      reply sets and matrix results
docs/             specs, acceptance records, results, papers
```

## Evidence in one block

```
content identity   identical kid across processes / devices / kernel rebuild / proposal removal
behavioral identity PCS = A x min(C); 80 executable-rule probes; judge kappa = 0.690 (60-item holdout)
human baseline     191 real human turns: question-first 10%, echo-first 98%
multi-turn         collapse rate 0.389 / 0.556; normalized first failure 0.657 / 0.635
performance        index 200k events in ~12 s; assembly p50 13 ms
```

## What this does not do

- no real long-term user data (synthetic scenarios and model-generated replies only)
- no month-scale replay
- no head-to-head comparison against other memory systems
- conclusions hold per conversation mode (emotional support / consultation); no automatic mode detection
- no real-time, audio or embodied driver yet (the projection layer is the hook, not an implementation)

See paper section 7.2 for the full list of what we do not claim.

## License

Apache-2.0. See [LICENSE](LICENSE).
