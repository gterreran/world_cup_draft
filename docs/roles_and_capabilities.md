# Roles and Capabilities

This document describes the roles supported by the World Cup Draft application and the permissions associated with each role.

The permission system is intentionally simple. Most permissions are determined dynamically based on the user's relationship to a specific league.

---

# Design Philosophy

The application follows two core principles:

1. Tournament information should be publicly accessible.
2. League management tools should be restricted to authorized users.

This allows anyone with a link to follow a league while ensuring that only commissioners can modify league data.

The application does not currently use a dedicated role model. Roles are determined from existing application data and Django's built-in user permissions.

---

# Roles

The application supports four conceptual roles:

```text
Platform Owner
Commissioner
Participant
Public Viewer
```

A user may have different roles in different leagues.

For example:

```text
Commissioner in League A
Participant in League B
Public Viewer in League C
```

---

# Platform Owner

A Platform Owner is a Django staff or superuser account.

Determined by:

```python
user.is_staff or user.is_superuser
```

Platform Owners have access to all leagues and administrative functionality.

Capabilities:

* View all leagues
* Manage any league
* Access all commissioner tools
* Edit match results
* Access Django Admin
* Override league-level restrictions when necessary

Platform Owners exist primarily for application administration and maintenance.

---

# Commissioner

A Commissioner is the user assigned as the owner of a league.

Determined by:

```python
league.commissioner == user
```

Commissioners control league configuration and management.

Capabilities:

* View league management pages
* Edit league settings
* Manage league members
* Manage assignments
* Lock and unlock assignments
* Run random assignments
* Manually assign teams
* Remove assignments
* Reveal and hide assignments
* Start and control animated drafts
* Reset assignments
* Import Sleeper managers
* Recompute league-specific data when required

Commissioners are responsible for running the league.

---

## Becoming a Commissioner

Any registered user may create a league.

The creator of a league automatically becomes its commissioner.

Commissioners retain all participant privileges while also gaining access to league management tools.

---

# Participant

A Participant is a user who belongs to a league through a LeagueMember entry.

Determined by:

```python
LeagueMember(user=user, league=league)
```

Participants can track leagues they belong to through their personal league dashboard.

Capabilities:

* View their league list
* Access leagues they participate in
* View league standings
* View revealed assignments
* Watch animated drafts

Participants cannot modify league configuration.

---

# Public Viewer

A Public Viewer is any visitor who is not acting as a commissioner or participant for a league.

Public viewers may be anonymous users or authenticated users without a relationship to the league.

The application intentionally allows broad visibility of league information.

Capabilities:

* View league detail pages if they have the link
* View league standings
* View revealed assignments
* View animated drafts
* View tournament schedule
* View group standings
* View tournament bracket

Public viewers cannot modify league data.

---

# League Visibility Model

League detail pages are intentionally public.

Anyone with a league URL may view:

* League standings
* Revealed assignments
* League membership information
* Draft results
* Draft viewer page

This behavior is similar to platforms such as Sleeper.

The application assumes that league URLs may be shared freely.

---

# Tournament Visibility Model

Tournament information is public.

The following pages are available without league membership:

* Tournament schedule
* Group stage standings
* Knockout bracket

Tournament pages belong to the tournament itself and are not tied to a specific league.

---

# League Dashboard

The league list page acts as a personal dashboard.

Anonymous users cannot access it.

Authenticated users see only leagues relevant to them.

Participants see:

```text
Leagues they participate in
```

Commissioners see:

```text
Leagues they commission
Leagues they participate in
```

Platform Owners see:

```text
All leagues
```

Each league row displays the user's role:

```text
Participant
Commissioner
Commissioner / Participant
Platform Owner
```

---

# Draft Permissions

Draft viewing is public.

Anyone with the draft link may watch the draft.

Draft control is restricted.

Only Commissioners and Platform Owners may:

* Start drafts
* Advance drafts
* Control reveals
* Reset draft state

Participants and Public Viewers are spectators.

---

# League Settings Permissions

League settings are restricted.

Only Commissioners and Platform Owners may:

* Edit league settings
* Modify member lists
* Configure Sleeper integration
* Change assignment configuration

Participants and Public Viewers have read-only access.

---

# Match Editing Permissions

Match result editing is highly restricted.

Only Platform Owners may:

* Edit tournament match results
* Override tournament outcomes
* Modify tournament progression manually

Commissioners do not have tournament-level editing permissions.

This separation prevents league managers from altering tournament results.

---

# Centralized Permission Helpers

Permissions are centralized in:

```text
leagues/permissions.py
```

Views should use the permission helpers rather than directly checking:

```python
league.commissioner == request.user
```

or

```python
request.user.is_staff
```

This ensures that permission logic remains consistent throughout the application.

Typical helper functions include:

```python
is_platform_owner()
is_commissioner()
is_participant()
can_manage_league()
can_control_draft()
can_edit_match_results()
```

---
