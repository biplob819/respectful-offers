# How Respectful Offers was built

The project was built the way its Tech Spec says, node by node, by an AI coding agent working
under a gated harness, with the owner making every judgement call that belonged to a person.

**The graph.** The [Tech Spec](../Respectful%20Offers%20Tech%20Spec.md) splits the work into
23 nodes ([`docs/graph/graph.md`](graph/graph.md)) and 125 capabilities
([`docs/graph/catalog.tsv`](graph/catalog.tsv)). A node may start only when every node it
depends on is green, and only with a spec, acceptance criteria and a task list
(`scripts/node_start.py`).

**The proof.** Every capability names the tests that prove it in five dimensions (logic,
contract, golden run, reproducibility, respect). `scripts/node_converge.py` runs twelve gates
per node: the proofs resolve, lint, types, unit, golden and respect tests, the secret and data
scans, a wheel build, tests changed with the code, and complete records. A node turns green
only after converging twice.

**The skeptic.** Before a node turned green, a separate verifier agent tried to disprove it:
recomputing every published number, probing for bypasses, reading the code against the
criteria. Its findings were fixed with tests and recorded: decisions D-1 to D-49 in the
[decision log](decisions.md) (the `OWNER` rows are the owner's rulings, such as the licence
reading and the confirmed simulator) and lessons L-1 to L-39 ([lessons](lessons.md)).

**What the skeptics caught.** A few examples: a deploy file that would have opened the passkey
gate (L-38); a demo that agreed with the full run on synthetic data and disagreed on real data,
because the real prices are a few plan prices, not a smooth spread (L-39, D-49); a licence
ruling written as settled fact when it is a reading (L-37); and, before the first real number
was reported, real decisions read end to end ([the decision review](../results/kkbox/decision-review.md)).

**What the owner decided.** The question the product asks, the two rules, the evaluation
design (a simulator rollout with validated off-policy estimates), hosting, the licence reading,
the simulator's values (frozen before the real run), and passkey protection for the demo.
