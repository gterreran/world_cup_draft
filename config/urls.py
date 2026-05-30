from django.contrib import admin
from django.urls import include, path

from leagues import views as league_views
from assignments import views as assignment_views
from scoring import views as scoring_views
from tournaments import views as tournament_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", league_views.home, name="home"),
    path("leagues/", league_views.league_list, name="league_list"),
    path("leagues/create/", league_views.league_create, name="league_create"),
    path("leagues/<slug:slug>/", league_views.league_detail, name="league_detail"),
    path(
        "leagues/<slug:slug>/members/create/",
        league_views.member_create,
        name="member_create",
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
        "leagues/<slug:slug>/schedule/",
        tournament_views.tournament_schedule,
        name="tournament_schedule",
    ),
    path(
        "leagues/<slug:slug>/groups/",
        tournament_views.group_stage,
        name="group_stage",
    ),
    path(
        "leagues/<slug:slug>/bracket/",
        tournament_views.bracket_stage,
        name="bracket_stage",
    ),
]