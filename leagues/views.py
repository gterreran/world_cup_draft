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
from scoring.services import recompute_league_standings
from scoring.projections import (
    ensure_projection_entries_exist,
    get_projection_entries_by_member_id,
    mark_projection_entries_stale,
)
from scoring.defaults import default_scoring_config, default_tiebreaker_config
from .forms import LeagueTiebreakerSettingsForm

from django.contrib import messages

from integrations.sleeper import SleeperAPIError, get_rosters, get_users

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

        if form.is_valid():
            league = form.save(commit=False)
            league.commissioner = request.user
            league.slug = _unique_league_slug(league.name)
            league.scoring_config = default_scoring_config()
            league.tiebreaker_config = default_tiebreaker_config()
            league.save()

            LeagueMember.objects.create(
                league=league,
                user=request.user,
                display_name=request.user.get_username(),
            )

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

    ensure_projection_entries_exist(league)
    projections_by_member_id = get_projection_entries_by_member_id(league)

    return render(
        request,
        "leagues/league_detail.html",
        {
            "league": league,
            "members": members,
            "assignments": assignments,
            "standings": standings,
            "projections_by_member_id": projections_by_member_id,
        },
    )


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
def draft_order(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    standings = league.standings.select_related("member").order_by(
        "current_rank",
        "-points",
        "member__display_name",
    )

    assignments = league.team_assignments.select_related(
        "member",
        "national_team",
    ).order_by(
        "member__display_name",
        "national_team__pot",
        "national_team__name",
    )

    teams_by_member = {}
    for assignment in assignments:
        teams_by_member.setdefault(assignment.member_id, []).append(
            assignment.national_team
        )

    return render(
        request,
        "leagues/draft_order.html",
        {
            "league": league,
            "standings": standings,
            "teams_by_member": teams_by_member,
        },
    )

@login_required
def member_update(request, slug: str, member_id: int):
    league = get_object_or_404(League, slug=slug)
    member = get_object_or_404(LeagueMember, id=member_id, league=league)

    if league.commissioner != request.user:
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
def league_tiebreaker_settings(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        form = LeagueTiebreakerSettingsForm(request.POST, league=league)

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
        form = LeagueTiebreakerSettingsForm(league=league)

    return render(
        request,
        "leagues/league_tiebreaker_settings.html",
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
        return redirect("league_detail", slug=league.slug)

    if not league.sleeper_league_id:
        messages.error(request, "Add a Sleeper league ID in league settings first.")
        return redirect("league_settings", slug=league.slug)

    try:
        sleeper_users = get_users(league.sleeper_league_id)
        sleeper_rosters = get_rosters(league.sleeper_league_id)
    except SleeperAPIError as exc:
        messages.error(request, str(exc))
        return redirect("league_detail", slug=league.slug)

    created_count = 0
    updated_count = 0

    for sleeper_user in sleeper_users:
        sleeper_user_id = sleeper_user.get("user_id")
        display_name = (
            sleeper_user.get("display_name")
            or sleeper_user.get("username")
            or sleeper_user.get("metadata", {}).get("team_name")
            or f"Sleeper user {sleeper_user_id}"
        )

        roster_id_by_owner_id = {
            roster.get("owner_id"): str(roster.get("roster_id"))
            for roster in sleeper_rosters
            if roster.get("owner_id") is not None
        }

        if not sleeper_user_id:
            continue

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

    messages.success(
        request,
        f"Imported Sleeper members: {created_count} created, {updated_count} updated.",
    )

    return redirect("league_detail", slug=league.slug)