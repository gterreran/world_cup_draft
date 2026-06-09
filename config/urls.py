from django.contrib import admin
from django.urls import include, path
from django.http import HttpResponse

from leagues import views as league_views
from assignments import views as assignment_views
from drafts import views as draft_views
from scoring import views as scoring_views
from tournaments import views as tournament_views

def healthz(request):
    return HttpResponse("ok", content_type="text/plain")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", league_views.home, name="home"),
    path("leagues/", league_views.league_list, name="league_list"),
    path("leagues/create/", league_views.league_create, name="league_create"),
    path("leagues/<slug:slug>/", league_views.league_detail, name="league_detail"),
    path("leagues/<slug:slug>/follow/", league_views.follow_league, name="follow_league"),
    path("leagues/<slug:slug>/unfollow/", league_views.unfollow_league, name="unfollow_league"),
    path(
        "leagues/<slug:slug>/members/create/",
        league_views.member_create,
        name="member_create",
    ),
    path(
        "leagues/<slug:slug>/assignments/",
        assignment_views.assignment_management,
        name="assignment_management",
    ),
    path(
        "leagues/<slug:slug>/assignments/reset/",
        assignment_views.reset_assignment_view,
        name="reset_assignments",
    ),
    path(
        "leagues/<slug:slug>/assignments/manual/",
        assignment_views.manual_assignment_create,
        name="manual_assignment_create",
    ),
    path(
        "leagues/<slug:slug>/assignments/<int:assignment_id>/delete/",
        assignment_views.manual_assignment_delete,
        name="manual_assignment_delete",
    ),
    path(
        "leagues/<slug:slug>/assignments/reveal-all/",
        assignment_views.assignment_reveal_all,
        name="assignment_reveal_all",
    ),
    path(
        "leagues/<slug:slug>/assignments/hide-all/",
        assignment_views.assignment_hide_all,
        name="assignment_hide_all",
    ),
    path(
        "leagues/<slug:slug>/assignments/<int:assignment_id>/reveal/",
        assignment_views.assignment_reveal,
        name="assignment_reveal",
    ),
    path(
        "leagues/<slug:slug>/assignments/<int:assignment_id>/hide/",
        assignment_views.assignment_hide,
        name="assignment_hide",
    ),
    path(
        "leagues/<slug:slug>/assign/random/",
        assignment_views.random_assignment,
        name="random_assignment",
    ),
    path(
        "leagues/<slug:slug>/standings/recompute/",
        scoring_views.recompute_standings,
        name="recompute_standings",
    ),
    path(
        "leagues/<slug:slug>/projections/recompute/",
        scoring_views.recompute_projections,
        name="recompute_projections",
    ),
    path(
        "leagues/<slug:slug>/matches/",
        tournament_views.match_list,
        name="match_list",
    ),
    path(
        "leagues/<slug:slug>/matches/<int:match_id>/edit/",
        tournament_views.match_result_edit,
        name="match_result_edit",
    ),
    path(
        "leagues/<slug:slug>/draft-presentation/",
        league_views.draft_presentation,
        name="draft_presentation",
    ),
    path(
        "leagues/<slug:slug>/draft/live/",
        league_views.draft_live,
        name="draft_live",
    ),
    path(
        "leagues/<slug:slug>/draft/state/",
        draft_views.draft_state,
        name="draft_state",
    ),
    path(
        "leagues/<slug:slug>/draft/start/",
        draft_views.draft_start,
        name="draft_start",
    ),
    path(
        "leagues/<slug:slug>/draft/advance/",
        draft_views.draft_advance,
        name="draft_advance",
    ),
    path(
        "leagues/<slug:slug>/draft/reset/",
        draft_views.draft_reset,
        name="draft_reset",
    ),
    path(
        "leagues/<slug:slug>/draft/autoplay/",
        draft_views.draft_autoplay,
        name="draft_autoplay",
    ),
    path(
        "leagues/<slug:slug>/members/<int:member_id>/edit/",
        league_views.member_update,
        name="member_update",
    ),
    path(
        "leagues/<slug:slug>/members/<int:member_id>/delete/",
        league_views.member_delete,
        name="member_delete",
    ),
    path(
        "leagues/<slug:slug>/settings/",
        league_views.league_settings,
        name="league_settings",
    ),
    path(
        "leagues/<slug:slug>/settings/scoring/",
        league_views.league_scoring_settings,
        name="league_scoring_settings",
    ),
    path(
        "leagues/<slug:slug>/lock/",
        league_views.lock_assignments,
        name="lock_assignments",
    ),
    path(
        "leagues/<slug:slug>/unlock/",
        league_views.unlock_assignments,
        name="unlock_assignments",
    ),
    path(
        "leagues/<slug:slug>/import/sleeper-members/",
        league_views.import_sleeper_members,
        name="import_sleeper_members",
    ),
    path(
        "tournaments/<slug:tournament_slug>/schedule/",
        tournament_views.tournament_schedule,
        name="tournament_schedule",
    ),
    path(
        "tournaments/<slug:tournament_slug>/groups/",
        tournament_views.group_stage,
        name="group_stage",
    ),
    path(
        "tournaments/<slug:tournament_slug>/bracket/",
        tournament_views.bracket_stage,
        name="bracket_stage",
    ),
]