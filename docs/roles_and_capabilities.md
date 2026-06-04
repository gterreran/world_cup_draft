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
Registered User
Anonymous Visitor
```

---

# Identity Model

The application intentionally separates app accounts from fantasy managers.

There are three distinct concepts:

```text
User
Profile
LeagueMember
```

User
: Django authentication account.

Profile
: Stores user-specific preferences and followed leagues.

LeagueMember
: Represents a fantasy manager/team slot inside a league.

A LeagueMember is not automatically associated with a User account.

For example, importing managers from Sleeper creates LeagueMember records but does not create User accounts.

This separation allows leagues to be imported and managed independently of application registration.

---

# Platform Owner

A Platform Owner is a Django staff or superuser account.

Determined by:

```python
user.is_staff or user.is_superuser
```

Capabilities:

* View all leagues
* Manage any league
* Access all commissioner tools
* Edit match results
* Access Django Admin
* Override league-level restrictions when necessary

---

# Commissioner

A Commissioner is the user assigned as the owner of a league.

Determined by:

```python
league.commissioner == user
```

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

## Becoming a Commissioner

Any registered user may create a league.

The creator of a league automatically becomes its commissioner.

Commissioners automatically see their leagues in their dashboard and gain access to league management tools.

---

# Registered User

A Registered User is an authenticated account in the application.

Registered users may:

* Follow leagues
* Maintain a personal league dashboard
* Create leagues
* Become commissioners
* Access account-specific features

Registered users do not automatically become fantasy managers inside a league.

League membership and application accounts are intentionally independent concepts.

---

# Registration

Anonymous visitors may create an account using the signup page.

Once registered, a Profile is automatically created for the user.

The Profile stores user-specific preferences and followed leagues.

Registration is optional for viewing public league and tournament pages.

---

# Following Leagues

Registered users may follow leagues.

Following a league adds that league to the user's personal dashboard.

This relationship is stored through the user's Profile and is independent of fantasy league membership.

A user may:

* Follow a league
* Unfollow a league
* Follow multiple leagues
* Follow leagues without participating in them

---

# Anonymous Visitor

An Anonymous Visitor is any user who is not logged in.

Capabilities:

* View league detail pages if they have the link
* View league standings
* View revealed assignments
* View animated drafts
* View tournament schedule
* View group standings
* View tournament bracket

---

# League Visibility Model

League detail pages are intentionally public.

Anyone with a league URL may view:

* League standings
* Revealed assignments
* League membership information
* Draft results
* Draft viewer page

This behavior is similar to Sleeper.

---

# Tournament Visibility Model

Tournament information is public.

The following pages are available without authentication:

* Tournament schedule
* Group stage standings
* Knockout bracket

Tournament pages belong to the tournament itself and are not tied to a specific league.

---

# League Dashboard

The league dashboard acts as a personalized entry point.

Anonymous visitors cannot access it.

Registered users see:

* Leagues they follow
* Leagues they commission

Commissioners automatically see their own leagues.

Platform Owners may view all leagues.

Viewing a league through a direct URL does not automatically add that league to the dashboard.

A user must explicitly follow the league.

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

---

# League Settings Permissions

Only Commissioners and Platform Owners may:

* Edit league settings
* Modify member lists
* Configure Sleeper integration
* Change assignment configuration

---

# Match Editing Permissions

Only Platform Owners may:

* Edit tournament match results
* Override tournament outcomes
* Modify tournament progression manually

Commissioners do not have tournament-level editing permissions.

---

# Centralized Permission Helpers

Permissions are centralized in:

```text
leagues/permissions.py
```

Typical helper functions include:

```python
is_platform_owner()
is_commissioner()
can_manage_league()
can_control_draft()
can_edit_match_results()
```
