import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date, parse_datetime

from tournaments.models import Match, NationalTeam, Tournament


class Command(BaseCommand):
    help = "Import tournament schedule matches from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            type=str,
            help="Path to the tournament schedule JSON file.",
        )
        parser.add_argument(
            "--allow-missing-teams",
            action="store_true",
            help=(
                "Do not fail if a named team cannot be found. "
                "The team name will be stored as a slot label instead."
            ),
        )

    def handle(self, *args, **options):
        json_path = Path(options["json_path"])
        allow_missing = options["allow_missing_teams"]

        if not json_path.exists():
            raise CommandError(f"File does not exist: {json_path}")

        with json_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        tournament_slug = payload["tournament_slug"]
        match_rows = payload["matches"]

        try:
            tournament = Tournament.objects.get(slug=tournament_slug)
        except Tournament.DoesNotExist as exc:
            raise CommandError(
                f"Tournament does not exist: {tournament_slug}. "
                "Import teams/tournament first."
            ) from exc

        created_count = 0
        updated_count = 0
        missing_teams = []

        for row in match_rows:
            home_team, home_slot = self._resolve_team_or_slot(
                tournament=tournament,
                team_name=row.get("home_team"),
                slot=row.get("home_slot", ""),
                allow_missing=allow_missing,
                missing_teams=missing_teams,
            )
            away_team, away_slot = self._resolve_team_or_slot(
                tournament=tournament,
                team_name=row.get("away_team"),
                slot=row.get("away_slot", ""),
                allow_missing=allow_missing,
                missing_teams=missing_teams,
            )

            kickoff_time = None
            if row.get("kickoff_time"):
                kickoff_time = parse_datetime(row["kickoff_time"])
                if kickoff_time is None:
                    raise CommandError(
                        f"Invalid kickoff_time for match {row['match_number']}: "
                        f"{row['kickoff_time']}"
                    )

            match_date = None
            if row.get("match_date"):
                match_date = parse_date(row["match_date"])
                if match_date is None:
                    raise CommandError(
                        f"Invalid match_date for match {row['match_number']}: "
                        f"{row['match_date']}"
                    )

            match_group = self._resolve_group(
                row=row,
                home_team=home_team,
                away_team=away_team,
            )

            _, created = Match.objects.update_or_create(
                tournament=tournament,
                match_number=row["match_number"],
                defaults={
                    "stage": row["stage"],
                    "group": match_group,
                    "status": row.get("status", Match.Status.SCHEDULED),
                    "match_date": match_date,
                    "kickoff_time": kickoff_time,
                    "venue": row.get("venue", ""),
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_slot": home_slot,
                    "away_slot": away_slot,
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        if missing_teams and not allow_missing:
            unique_missing = sorted(set(missing_teams))
            raise CommandError(
                "Could not resolve these teams: " + ", ".join(unique_missing)
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported schedule for {tournament}: "
                f"{created_count} created, {updated_count} updated."
            )
        )


    def _resolve_group(self, *, row, home_team, away_team) -> str:
        """Return the group to store on a match row.

        The schedule JSON is the source of truth, but this fallback makes the
        importer robust to older or hand-edited schedule files and also helps
        repair existing rows when the command is re-run.
        """
        explicit_group = row.get("group", "") or ""

        if explicit_group:
            return explicit_group

        if row.get("stage") != Match.Stage.GROUP:
            return ""

        home_group = home_team.group if home_team else ""
        away_group = away_team.group if away_team else ""

        if home_group and away_group and home_group != away_group:
            raise CommandError(
                f"Match {row['match_number']} has teams from different groups: "
                f"{home_team.name} is in {home_group}, "
                f"{away_team.name} is in {away_group}."
            )

        return home_group or away_group or ""

    def _resolve_team_or_slot(
        self,
        *,
        tournament,
        team_name,
        slot,
        allow_missing,
        missing_teams,
    ):
        if not team_name:
            return None, slot or ""

        try:
            team = NationalTeam.objects.get(
                tournament=tournament,
                name=team_name,
            )
            return team, ""
        except NationalTeam.DoesNotExist:
            missing_teams.append(team_name)
            if allow_missing:
                return None, team_name
            return None, slot or team_name
