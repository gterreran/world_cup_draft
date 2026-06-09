# Max-Points Projection Engine

This document describes how the World Cup Draft app computes cached max-points projections for each league manager.

The implementation lives mainly in:

```text
scoring/projections.py
```

It also reuses tournament-level logic from:

```text
tournaments/mathematical_status.py
tournaments/bracket_nodes.py
tournaments/third_place.py
```

---

# Goal

For each league member, compute:

```text
current points
+ maximum remaining points still reachable
= maximum possible points
```

The projection is manager-local. It asks:

```text
What is the best possible future for this manager's assigned teams?
```

It does not try to compute one globally consistent tournament path across all fantasy managers.

This is intentional. Max-points projections are best-case ceilings.

---

# Stored Output

Projection results are cached in:

```text
scoring.ProjectionEntry
```

One row exists per league member.

Important fields:

```text
current_points
remaining_possible_points
max_possible_points
best_case_slots
is_stale
stale_reason
computed_at
```

The league detail page reads these cached rows. It does not recompute projections during page rendering.

---

# Public API

The public recompute function is:

```python
recompute_projection_entries(league)
```

This recomputes and stores every member's projection for one league.

The background worker calls this function after consuming a queued projection job.

The synchronous management command still exists for maintenance/debugging:

```bash
python manage.py recompute_projections
python manage.py recompute_projections <league_slug>
```

---

# High-Level Formula

For one manager:

```text
remaining_possible_points
    = best future group points
    + best future qualification points
    + best future knockout points
```

Then:

```text
max_possible_points
    = current_points
    + remaining_possible_points
```

---

# Why the Engine Uses Compact Options

The first projection implementation enumerated raw remaining group-result scenarios. Early in the tournament, this exploded quickly because each group has many possible outcome combinations and each manager owns several teams.

The current implementation compresses the search space.

Instead of keeping every scenario that leads to the same fantasy-relevant future, each team is reduced to compact future options such as:

```text
eliminated
1A
2A
third-place bracket node
```

A team's future option captures only what matters for fantasy max scoring:

```text
source position
source slot
concrete bracket node
qualification bonus
best group points compatible with that position
```

This turns early-tournament products from hundreds of thousands of combinations per manager into roughly hundreds or low thousands.

---

# TeamProjectionOption

The central internal object is `TeamProjectionOption`.

It represents one fantasy-distinct future for one national team.

Conceptually it contains:

```text
team_id
source_position
source_slot
bracket_node_id
display_slot
qualified
qualification_bonus
group_future_points
third_group
```

Examples:

```text
position=1, source_slot=1A, node=R32-07-H, group_points=9, qualification=3
position=2, source_slot=2C, node=R32-04-A, group_points=7, qualification=3
position=3, source_slot=3AEHIJ, node=R32-09-A, group_points=6, qualification=3
eliminated, no bracket node, group_points=max compatible non-qualification points
```

---

# Group-Stage Logic

The projection engine does not independently simulate group standings from scratch.

It reuses:

```python
_compute_group_outcome_envelope(tournament, group)
```

from `tournaments.mathematical_status`.

For each group, this produces a `GroupOutcomeEnvelope` containing each team's `TeamOutcomeEnvelope`.

The enriched team envelope provides:

```text
possible_positions
position_outcomes
best/worst third-place information
```

For projections, the most important addition is the position-level outcome data.

For a selected position, the engine asks:

```text
What remaining W/D/L records can lead this team to that position?
```

Then it chooses the best fantasy group points compatible with that position.

This matters because a team cannot receive maximum group points for every finishing position. For example, a team finishing 3rd cannot also receive the fantasy points for winning all three group games in a normal group.

---

# Position-Compatible Group Points

Group points are not calculated globally as:

```text
win every remaining group match
```

That would be too optimistic.

Instead:

```text
position 1 option → best group points among records compatible with finishing 1st
position 2 option → best group points among records compatible with finishing 2nd
position 3 option → best group points among records compatible with finishing 3rd
eliminated option → best group points among records compatible with non-qualification
```

This is why a best option combo can intentionally place a team 2nd or 3rd: losing a few group points may unlock a much better bracket path.

---

# Bracket Nodes

The projection engine uses the utility layer in:

```text
tournaments/bracket_nodes.py
```

The bracket-node layer keeps both:

```text
source slot: 1A, 2C, 3AEHIJ, W79, L101
concrete node: M079:H, M075:A, etc.
```

Human-friendly labels look like:

```text
R32-07-H
R32-04-A
```

This allows projections to reason about the concrete bracket graph while preserving the original FIFA-style slot labels.

---

# Third-Place Qualification

Third-place teams are the hardest part.

The engine uses the FIFA third-place allocation table from:

```text
tournaments/third_place.py
```

For a third-place option to be valid, there must be at least one FIFA table row where:

```text
the required third-place group qualifies
and the selected source slot matches the FIFA allocation for that row
```

For combinations with multiple owned third-place teams, the selected third-place options must be mutually compatible with the same FIFA table row.

The current implementation validates bracket-slot compatibility against the FIFA table.

A possible future refinement is to also validate every third-place option combination against exact cross-group third-place point relationships. The current engine is intentionally optimistic for max-ceiling projections.

---

# Manager Option Product

For each manager:

1. Load the manager's assigned teams.
2. Build compact option lists for each team.
3. Iterate over the product of those lists.
4. Reject invalid combinations.
5. Compute group + qualification + knockout points.
6. Keep the best result.

The product is now compact. Example option group sizes early in the tournament may look like:

```text
[5, 6, 8, 9]
```

rather than dozens of raw group scenario variants per team.

---

# Combination Validation

Each option combination is rejected if it violates obvious constraints:

```text
duplicate concrete bracket node
duplicate source slot
third-place choices incompatible with the FIFA allocation table
```

If all teams are eliminated, the combination can still be considered because group-stage points may still contribute to the manager's ceiling.

---

# Knockout Simulation

For a valid bracket placement, the engine searches the future knockout graph.

Rules:

```text
owned team vs non-owned team → owned team may advance
owned team vs owned team → choose the branch with the best downstream total
non-owned vs non-owned → no fantasy points, no owned team advances
```

The model is intentionally manager-local and optimistic. Non-owned teams are treated as beatable placeholders whenever the bracket allows it.

This means several managers can each have a best-case path where all four of their teams reach the semifinals. Those paths do not need to be mutually compatible across different managers.

---

# Knockout Scoring Components

Future knockout points are stored and logged as components.

Examples:

```text
knockout win
champion bonus
runner-up bonus
third-place bonus
fourth-place bonus
```

With the default scoring observed during testing, the maximum knockout path for four teams reaching the semifinals is:

```text
Round of 32 wins:     4 × 4 = 16
Round of 16 wins:     4 × 4 = 16
Quarterfinal wins:    4 × 4 = 16
Semifinal wins:       2 × 4 = 8
Third-place match:    4 + 3 + 2 = 9
Final:                4 + 8 + 5 = 17

Total knockout = 82
```

This explains why many managers can share the same knockout ceiling while still differing in group-stage ceiling.

---

# Best-Case Logging

Verbose projection runs print:

```text
member name
assigned teams
option group sizes
product count
best group points
best qualification points
best knockout points
best option combo
best knockout path
```

This logging is useful for validating the projection engine and understanding surprising results.

The logs can show cases where a manager deliberately prefers a 2nd-place or 3rd-place group finish because it creates a better bracket spread.

---

# Relationship to Background Workers

The projection engine itself is synchronous Python code.

The background worker decides when and where it runs.

```text
request_projection_recompute()
    queues a job

run_projection_worker
    consumes the job
    calls recompute_projection_entries(league)
```

The projection engine should not know whether it was called by:

```text
management command
worker
future live-score service
manual shell test
```

---

# Intentional Limitations

The projection is a ceiling, not a forecast.

It does not estimate probability.

It does not try to make different managers' best-case paths mutually compatible.

It treats non-owned teams as beatable whenever this helps the manager-local maximum.

It currently validates third-place bracket placement through the FIFA table, but does not fully optimize cross-group third-place point relationships for all selected third-place teams.

These choices are appropriate for a max-points projection. If the app later adds probability-based projections, that should be a separate feature.

---

# Design Summary

The current projection engine is built around this separation:

```text
tournament math layer
    determines reachable group outcomes

bracket-node layer
    maps source slots to concrete bracket nodes

projection layer
    builds compact fantasy options
    searches manager-local best bracket paths
    writes cached ProjectionEntry rows
```

This keeps the calculation fast, understandable, and reusable by the background worker.
