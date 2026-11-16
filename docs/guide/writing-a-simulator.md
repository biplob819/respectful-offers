# Writing a simulator config

Your data has no offers in it, so how members respond to an offer is an assumption. The
simulator file (`simulator.yaml`) states that assumption openly, and every result is reported
under all of its variants. Read the comments in the file: each value says what it means.

- **Segments.** Each member has a hidden segment: `sure_thing` (renews anyway),
  `persuadable` (an offer can change their mind), `lost_cause` and `sleeping_dog` (an offer
  makes leaving more likely). The mix depends on risk band and listening trend.
- **Actions.** No offer, a content nudge, a one-month discount and a plan change, each with an
  acceptance rate and an exposure effect per segment.
- **Variants.** At least `conservative`, `central` and `optimistic`, ordered as their names say.

`offers prereg` checks the direction rules (for example, a discount never helps a lost cause
more than a persuadable) and freezes the file by its sha256. Change any value afterwards and
evaluation refuses to run until you register again with a reason, or run with `--exploratory`.
Register before you look at results: that is what makes them trustworthy.
