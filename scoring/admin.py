from django.contrib import admin

from .models import ProjectionEntry, ProjectionJobState, ProjectionWorkerStatus, StandingEntry


@admin.register(StandingEntry)
class StandingEntryAdmin(admin.ModelAdmin):
    list_display = ("league", "member", "current_rank", "points", "wins", "draws", "losses", "goal_difference", "goals_scored")
    list_filter = ("league",)
    search_fields = ("member__display_name",)


@admin.register(ProjectionEntry)
class ProjectionEntryAdmin(admin.ModelAdmin):
    list_display = (
        "league",
        "member",
        "max_possible_points",
        "remaining_possible_points",
        "is_stale",
        "computed_at",
    )
    list_filter = ("league", "is_stale")
    search_fields = ("member__display_name", "league__name", "league__slug")


@admin.register(ProjectionJobState)
class ProjectionJobStateAdmin(admin.ModelAdmin):
    list_display = (
        "league",
        "status",
        "requested_at",
        "started_at",
        "last_heartbeat_at",
        "finished_at",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = ("league__name", "league__slug", "last_job_id")
    readonly_fields = (
        "last_job_id",
        "requested_at",
        "started_at",
        "last_heartbeat_at",
        "finished_at",
        "error_message",
        "updated_at",
    )


@admin.register(ProjectionWorkerStatus)
class ProjectionWorkerStatusAdmin(admin.ModelAdmin):
    list_display = (
        "worker_name",
        "status_label",
        "started_at",
        "last_seen_at",
        "updated_at",
    )
    search_fields = ("worker_name",)
    readonly_fields = (
        "worker_name",
        "started_at",
        "last_seen_at",
        "updated_at",
    )
