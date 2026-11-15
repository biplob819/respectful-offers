# A2.2 acceptance criteria

**SIM-01 — response model**
- Hand-checked cases with forced acceptance: an accepted discount renews at (1 − fraction) × price with the fraction recorded as cost; an accepted plan change renews at the ratio and keeps it in later periods, and a second plan change is refused; a declined offer applies its exposure effect; an engaged nudge adds its acceptance effect; a shown action is never `not_shown` and `no_offer` always is. Over many members, no-offer renewal matches 1 − risk and sleeping dogs shown a discount renew less than under no offer.

**SIM-02 — three variants**
- `configs/simulator.yaml` loads with conservative, central and optimistic variants, passes the direction rules, explains every value in comments, and says plainly it awaits the owner's confirmation.

**SIM-03 — common random numbers**
- A member's response draws are identical whatever other members are simulated with them, in any order, and whichever policy chose the action; segments are drawn once per member from the member's own stream.

**SIM-04 — exact oracle**
- `expected_reward` matches the Monte Carlo mean of `respond` for every action within 3 standard errors on 200,000 members; averaging `expected_reward_by_segment` over the segment mix reproduces `expected_reward` exactly.

**SIM-05 — pre-registration**
- `offers prereg` records the YAML's sha256, date, scope (`synthetic` or `real`) and criteria, and appends the registration to the decision log; replacing a different registration needs a reason; evaluation status is `preregistered` only for the registered file under a scope that covers the data (a synthetic registration never certifies KKBox data), refuses a changed, missing or unregistered file, and is `exploratory` only when asked; registering a file that breaks the direction rules is refused, and an `allow_unconventional` registration is stamped.

**SIM-06 — direction and ordering rules**
- Each rule is refused on a crafted config (persuadable harmed, sleeping dog helped by any offer or nudge, neutral segment moved, variants out of order or missing, a nonzero nudge cost), with a message naming variant and rule; `allow_unconventional: true` lets it through.
