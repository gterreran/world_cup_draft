"""Template context helpers for tournament-wide navigation."""

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Case, IntegerField, Value, When

from .models import Tournament


def public_tournament(request):
    """Expose the primary public tournament to base templates.

    The app can technically contain multiple tournaments, but the public top-bar
    links should point to the current/showcase tournament. A configured slug is
    preferred; otherwise we fall back to the active/upcoming/latest tournament.
    """

    tournament = None
    configured_slug = getattr(settings, "PUBLIC_TOURNAMENT_SLUG", "").strip()

    try:
        if configured_slug:
            tournament = Tournament.objects.filter(slug=configured_slug).first()

        if tournament is None:
            tournament = (
                Tournament.objects.annotate(
                    status_sort=Case(
                        When(status=Tournament.Status.ACTIVE, then=Value(0)),
                        When(status=Tournament.Status.UPCOMING, then=Value(1)),
                        default=Value(2),
                        output_field=IntegerField(),
                    )
                )
                .order_by("status_sort", "-year", "name")
                .first()
            )
    except DatabaseError:
        # Keep the base template renderable during setup/migration windows.
        tournament = None

    return {"public_tournament": tournament}
