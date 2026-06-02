from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from .forms import (
    LeagueCreateForm,
    LeagueMemberCreateForm,
    LeagueScoringSettingsForm,
    LeagueSettingsForm,
)
from .models import League, LeagueMember
from scoring.services import (
    compute_team_contribution,
    recompute_league_standings,
    team_is_eliminated_from_scoring,
)
from scoring.projections import (
    ensure_projection_entries_exist,
    get_projection_entries_by_member_id,
    mark_projection_entries_stale,
)
from scoring.defaults import default_scoring_config, default_tiebreaker_config

from django.contrib import messages

from integrations.sleeper import SleeperAPIError, get_rosters, get_users
from drafts.services import get_draft_picks, serialize_draft_state

def home(request):
    return render(request, "base/home.html")


@login_required
def league_list(request):
    leagues = League.objects.filter(members__user=request.user).distinct()
    commissioned = League.objects.filter(commissioner=request.user)

    return render(
        request,
        "leagues/league_list.html",
        {
            "leagues": leagues,
            "commissioned": commissioned,
        },
    )


@login_required
def league_create(request):
    if request.method == "POST":
        form = LeagueCreateForm(request.POST)
        should_import_sleeper = "create_with_sleeper" in request.POST

        if form.is_valid():
            sleeper_league_id = form.cleaned_data.get("sleeper_league_id", "").strip()

            if should_import_sleeper and not sleeper_league_id:
                form.add_error(
                    "sleeper_league_id",
                    "Enter a Sleeper league ID before importing managers.",
                )
            elif should_import_sleeper:
                try:
                    sleeper_users = get_users(sleeper_league_id)
                    sleeper_rosters = get_rosters(sleeper_league_id)
                except SleeperAPIError as exc:
                    form.add_error("sleeper_league_id", str(exc))
                else:
                    league = _create_league_from_form(form, request.user)
                    created_count, updated_count = _sync_sleeper_members(
                        league=league,
                        sleeper_users=sleeper_users,
                        sleeper_rosters=sleeper_rosters,
                    )
                    messages.success(
                        request,
                        "League created. Imported Sleeper managers: "
                        f"{created_count} created, {updated_count} updated.",
                    )
                    return redirect("league_detail", slug=league.slug)
            else:
                league = _create_league_from_form(form, request.user)
                messages.success(request, "League created.")
                return redirect("league_detail", slug=league.slug)
    else:
        form = LeagueCreateForm()

    return render(request, "leagues/league_create.html", {"form": form})


@login_required
def league_detail(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    members = league.members.all()
    assignments = league.team_assignments.select_related(
        "member",
        "national_team",
    ).order_by(
        "member__display_name",
        "national_team__pot",
        "national_team__name",
    )
    standings = league.standings.select_related("member").order_by(
        "current_rank",
        "-points",
        "member__display_name",
    )

    assignment_cards_by_member = _assignment_cards_by_member(
        league=league,
        assignments=assignments,
    )

    ensure_projection_entries_exist(league)
    projections_by_member_id = get_projection_entries_by_member_id(league)

    return render(
        request,
        "leagues/league_detail.html",
        {
            "league": league,
            "members": members,
            "assignments": assignments,
            "assignment_cards_by_member": assignment_cards_by_member,
            "standings": standings,
            "projections_by_member_id": projections_by_member_id,
        },
    )



def _assignment_cards_by_member(*, league: League, assignments) -> dict[int, list[dict]]:
    """Build display-ready assigned-team cards for the league dashboard."""
    cards_by_member: dict[int, list[dict]] = {}

    for assignment in assignments:
        team = assignment.national_team
        contribution = compute_team_contribution(league, team)

        cards_by_member.setdefault(assignment.member_id, []).append(
            {
                "assignment": assignment,
                "team": team,
                "points": contribution["points"],
                "wins": contribution["wins"],
                "draws": contribution["draws"],
                "losses": contribution["losses"],
                "goal_difference": contribution["goal_difference"],
                "goals_scored": contribution["goals_scored"],
                "teams_advanced": contribution["teams_advanced"],
                "is_eliminated": team_is_eliminated_from_scoring(league, team),
            }
        )

    return cards_by_member

def _unique_league_slug(name: str) -> str:
    base_slug = slugify(name) or "league"
    slug = base_slug
    counter = 2

    while League.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


@login_required
def member_create(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        return redirect("league_detail", slug=league.slug)

    if league.is_setup_locked:
        messages.error(request, "Unlock the league before adding managers.")
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        form = LeagueMemberCreateForm(request.POST)

        if form.is_valid():
            member = form.save(commit=False)
            member.league = league
            member.save()

            return redirect("league_detail", slug=league.slug)
    else:
        form = LeagueMemberCreateForm()

    return render(
        request,
        "leagues/member_form.html",
        {
            "league": league,
            "form": form,
            "title": "Add Manager",
            "button_label": "Add manager",
        },
    )


@login_required
def draft_presentation(request, slug: str):
    """Show the animated draft reveal for the current team assignments."""
    league = get_object_or_404(League, slug=slug)
    picks = get_draft_picks(league)
    draft_state = serialize_draft_state(league)

    return render(
        request,
        "leagues/draft_presentation.html",
        {
            "league": league,
            "picks": picks,
            "draft_state": draft_state,
            "can_control": True,
            "is_live_view": False,
        },
    )


def draft_live(request, slug: str):
    """Public read-only live draft page."""
    league = get_object_or_404(League, slug=slug)

    picks = get_draft_picks(league)
    draft_state = serialize_draft_state(league)

    return render(
        request,
        "leagues/draft_presentation.html",
        {
            "league": league,
            "picks": picks,
            "draft_state": draft_state,
            "can_control": False,
            "is_live_view": True,
        },
    )


@login_required
def member_update(request, slug: str, member_id: int):
    league = get_object_or_404(League, slug=slug)
    member = get_object_or_404(LeagueMember, id=member_id, league=league)

    if league.commissioner != request.user:
        return redirect("league_detail", slug=league.slug)

    if league.is_setup_locked:
        messages.error(request, "Unlock the league before editing managers.")
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        form = LeagueMemberCreateForm(request.POST, instance=member)

        if form.is_valid():
            form.save()
            return redirect("league_detail", slug=league.slug)
    else:
        form = LeagueMemberCreateForm(instance=member)

    return render(
        request,
        "leagues/member_form.html",
        {
            "league": league,
            "member": member,
            "form": form,
            "title": "Edit Manager",
            "button_label": "Save manager",
        },
    )


@login_required
def member_delete(request, slug: str, member_id: int):
    league = get_object_or_404(League, slug=slug)
    member = get_object_or_404(LeagueMember, id=member_id, league=league)

    if league.commissioner != request.user:
        return redirect("league_detail", slug=league.slug)

    if league.is_setup_locked:
        messages.error(request, "Unlock the league before deleting managers.")
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        member.delete()
        return redirect("league_detail", slug=league.slug)

    return render(
        request,
        "leagues/member_confirm_delete.html",
        {
            "league": league,
            "member": member,
        },
    )


@login_required
def league_settings(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        form = LeagueSettingsForm(request.POST, instance=league)

        if form.is_valid():
            form.save()
            return redirect("league_detail", slug=league.slug)
    else:
        form = LeagueSettingsForm(instance=league)

    return render(
        request,
        "leagues/league_settings.html",
        {
            "league": league,
            "form": form,
        },
    )


@login_required
def lock_assignments(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        messages.error(request, "Only the commissioner can lock the league.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("league_detail", slug=league.slug)

    league.lock_assignments()
    messages.success(request, "League setup locked.")
    return redirect("league_detail", slug=league.slug)


@login_required
def unlock_assignments(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        messages.error(request, "Only the commissioner can unlock the league.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("league_detail", slug=league.slug)

    league.unlock_assignments()
    messages.success(
        request,
        "League setup unlocked. Existing assignments were preserved.",
    )
    return redirect("league_detail", slug=league.slug)


@login_required
def league_scoring_settings(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        form = LeagueScoringSettingsForm(request.POST, league=league)

        if form.is_valid():
            form.save()
            recompute_league_standings(league)
            mark_projection_entries_stale(
                league,
                reason="Scoring settings changed.",
            )
            messages.info(
                request,
                "Scoring settings changed. Max-points projections need to be recomputed.",
            )
            return redirect("league_detail", slug=league.slug)
    else:
        form = LeagueScoringSettingsForm(league=league)

    return render(
        request,
        "leagues/league_scoring_settings.html",
        {
            "league": league,
            "form": form,
        },
    )


@login_required
def import_sleeper_members(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        messages.error(request, "Only the commissioner can import Sleeper members.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("league_settings", slug=league.slug)

    if league.is_setup_locked:
        messages.error(request, "Unlock the league before importing Sleeper managers.")
        return redirect("league_settings", slug=league.slug)

    if not league.sleeper_league_id:
        messages.error(request, "Add a Sleeper league ID before importing managers.")
        return redirect("league_settings", slug=league.slug)

    try:
        created_count, updated_count = _import_sleeper_members_for_league(league)
    except SleeperAPIError as exc:
        messages.error(request, str(exc))
        return redirect("league_settings", slug=league.slug)

    messages.success(
        request,
        f"Imported Sleeper managers: {created_count} created, {updated_count} updated.",
    )
    return redirect("league_settings", slug=league.slug)


def _create_league_from_form(form: LeagueCreateForm, user) -> League:
    league = form.save(commit=False)
    league.commissioner = user
    league.slug = _unique_league_slug(league.name)
    league.scoring_config = default_scoring_config()
    league.tiebreaker_config = default_tiebreaker_config()
    league.save()
    return league


def _import_sleeper_members_for_league(league: League) -> tuple[int, int]:
    sleeper_users = get_users(league.sleeper_league_id)
    sleeper_rosters = get_rosters(league.sleeper_league_id)
    return _sync_sleeper_members(
        league=league,
        sleeper_users=sleeper_users,
        sleeper_rosters=sleeper_rosters,
    )


def _sync_sleeper_members(
    *,
    league: League,
    sleeper_users: list[dict],
    sleeper_rosters: list[dict],
) -> tuple[int, int]:
    roster_id_by_owner_id = {
        roster.get("owner_id"): str(roster.get("roster_id"))
        for roster in sleeper_rosters
        if roster.get("owner_id") is not None
    }

    created_count = 0
    updated_count = 0

    for sleeper_user in sleeper_users:
        sleeper_user_id = sleeper_user.get("user_id")

        if not sleeper_user_id:
            continue

        display_name = (
            sleeper_user.get("display_name")
            or sleeper_user.get("username")
            or sleeper_user.get("metadata", {}).get("team_name")
            or f"Sleeper user {sleeper_user_id}"
        )

        _, created = LeagueMember.objects.update_or_create(
            league=league,
            sleeper_user_id=sleeper_user_id,
            defaults={
                "display_name": display_name,
                "sleeper_roster_id": roster_id_by_owner_id.get(sleeper_user_id, ""),
            },
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

    return created_count, updated_count
