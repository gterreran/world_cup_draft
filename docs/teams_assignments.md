# Assignment Management and Reveal Logic

This document describes how team assignments work in the World Cup Draft app, including random assignment, manual commissioner controls, hidden/revealed assignments, and the relationship between assignments and the draft room.

---

## Core Concepts

The app separates two related but distinct concepts:

```text
assigned = which manager owns which national team
revealed = whether that assignment is visible to league participants/public viewers
```

This distinction is important.

Assignments can exist in the database before anyone can see them. This allows the app to safely generate all assignments up front, while still preserving the excitement of revealing teams one by one during the live draft.

The live draft does **not** dynamically decide which teams are assigned. Instead, it reveals assignments that already exist.

This keeps the random assignment logic reliable and avoids complicated late-round availability problems.

---

## Random Assignment

Random assignment still happens as an atomic app-side operation.

The assignment logic should:

- assign the required number of teams to each manager
- respect existing assignment constraints
- avoid assigning multiple teams from the same World Cup group to the same manager
- lock the league setup after random assignment
- mark projections stale
- reset draft state when appropriate

Random assignment should not reveal teams automatically unless a specific commissioner action requests that.

The commissioner can trigger the assignment in 2 ways:

1. By starting the live draft without any existing assignments
2. By clicking "Assign randomly" from the assignment management page

In both cases, all the assignments are immediately visible to the commissioner in the assignment management page, but they are hidden from participants and public viewers until revealed.

---

## Manual Assignment

Commissioners can manually assign unassigned teams to managers from the assignment management page.

Manual assignment should enforce the same core constraints as random assignment:

- a manager cannot exceed the configured number of assigned teams
- a manager cannot receive multiple teams from the same World Cup group
- assignments cannot be edited while assignment editing is locked

Manual assignment should also keep the related app state consistent by:

- marking projections stale
- resetting draft state when assignment changes require it
- recomputing standings or assignment-dependent state where needed

Manual assignments should default to hidden unless explicitly revealed.

---

## Assignment Visibility

Each team assignment has a reveal state.

```text
revealed = False
```

means the assignment exists but is hidden.

```text
revealed = True
```

means the assignment is visible.

Public and participant-facing pages should not expose hidden assignments. If a team is hidden, those pages should leave the corresponding space blank rather than saying "Hidden". This avoids revealing that teams have already been assigned.

Commissioners can see all assignments, including hidden ones.

---

## What Public Users and League Participants See

On public or participant-facing pages:

- revealed assignments are shown normally
- hidden assignments are not shown
- hidden assignments should appear as blank space, not as a "Hidden" label

This preserves the live draft surprise.

---

## What Commissioners See

Commissioners can see the full assignment state in the assignment management page.

On commissioner-facing pages, assignments should show whether each assigned team is:

```text
Hidden
```

or

```text
Revealed
```

Commissioners can use the assignment management tools to control visibility.

---

## Removing Assignments

Commissioners can remove individual assignments from the assignment management page.

Removing an assignment should:

- delete the assignment
- make the national team available again
- mark projections stale
- reset draft state when appropriate
- recompute assignment-dependent standings/state where needed

Removing an assignment is a commissioner-only action.

---

## Locking and Unlocking Assignments

The assignment lock controls whether assignment edits are allowed.

When assignments are locked:

- managers cannot be edited/imported
- assignments cannot be manually changed
- assignment setup is protected from accidental edits

When assignments are unlocked:

- commissioners can manage assignments
- commissioners can remove assignments
- commissioners can manually assign teams
- commissioners can regenerate/reset assignments

Locking and unlocking can be controlled from the assignment management page.

If the commissioner unlocks assignments from the assignment page, the user should remain on the assignment page after the action completes.

---

## Resetting Assignments

Commissioners can reset all assignments from the assignment management page.

Resetting assignments should:

- remove all team assignments
- unlock assignment editing
- reset draft state
- mark projections stale
- recompute assignment-dependent standings/state where needed

This replaces the need to rely on the `reset_assignments` management command during normal app use.

---

## Reveal Controls

Commissioners can reveal or hide assignments.

Reveal controls are centralized on the assignment management page.

Commissioner-facing pages may display whether assignments are hidden or revealed, but per-team reveal/hide buttons should not be duplicated everywhere. In particular, the league detail page should show the reveal state but should not include per-team reveal/hide controls.

Supported visibility actions:

```text
Reveal one assignment
Hide one assignment
Reveal all assignments
Hide all assignments
```

---

## Reveal All

`Reveal all` makes every existing assignment visible.

This is useful when the commissioner wants to skip the animated reveal flow or recover from a draft/reveal issue.

Reveal all should be available to commissioners from the assignment management page.

---

## Hide All

`Hide all` marks all assignments as hidden again.

This is useful before a draft starts or if the commissioner wants to reset the reveal experience.

However, `Hide all` should only be available when the draft is not currently ongoing.

Once the live draft is in progress, hiding all assignments could conflict with the live reveal experience, so the action should be blocked.

---

## Live Draft Integration

The live draft is now a reveal mechanism.

It should not dynamically generate the next available team during the animation.

Instead, the flow is:

```text
Commissioner starts live draft
    ↓
If no assignments exist, generate assignments
    ↓
Assignments are stored as hidden
    ↓
Draft reveals assignments one by one
    ↓
Each revealed assignment is marked revealed=True
    ↓
Viewers see the newly revealed team
```

This gives the draft the feeling of assigning teams live while keeping the underlying assignment logic safe and deterministic.

---

## Starting the Draft When Assignments Already Exist

If assignments already exist when the commissioner starts the live draft:

- the draft should use the existing assignments
- hidden assignments should be revealed through the draft sequence
- already revealed assignments should remain revealed

This supports workflows where the commissioner manually prepared assignments before draft night.

---

## Starting the Draft When No Assignments Exist

If the commissioner starts the live draft before assigning teams:

- the app should generate random assignments automatically
- those assignments should be hidden by default
- the draft should then reveal them one by one

This removes the awkward extra step where the commissioner first had to click "Assign randomly" and only then start the live draft.

From the user's perspective, the live draft feels like the moment the teams are assigned.

From the app's perspective, the assignments are still generated safely before the reveal begins.

---

## Assignment Management Page

The assignment management page is the main commissioner control center for assignments.

It should support:

- view all assignments
- see Hidden/Revealed state
- lock assignments
- unlock assignments
- reset all assignments
- regenerate random assignments
- manually assign teams
- remove individual assignments
- reveal one assignment
- hide one assignment
- reveal all assignments
- hide all assignments when allowed

This page is commissioner-only.

