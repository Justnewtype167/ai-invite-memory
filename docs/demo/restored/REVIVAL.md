# AI Invite capsule revival guide

events: 3
segments: 1
head: 61a5d72633d15bcabe068c9b356cbc7b7353d51593eeeeef68e9ea3f1078645c
sealed_at: 2026-10-29T08:10:27Z

## Event fields
- v: always 1
- id: ev_ + six decimal digits, globally increasing
- ep: segment name such as seg-0001
- t: UTC timestamp YYYY-MM-DDTHH:MM:SSZ
- type: turn
- role: user or assistant
- text: 1-8000 characters
- prev: hash of the previous event; 64 zeros for the first event
- hash: sha256(prev_ascii + LF + canonical_json_without_hash)

## Revival without this code (five steps, standard library only)
1. Open memory.aiem with zipfile and read every evidence/seg-*.jsonl entry.
2. Read each line in file order and parse it with json.loads.
3. Rebuild the body by dropping hash, sorting keys, using no spaces, UTF-8.
4. Check sha256(prev.encode('ascii') + b'\n' + body) == hash and prev == last hash.
5. Append text in event order; stop on the first mismatch and report that id.
