from django.core.management.base import BaseCommand, CommandError

from tournaments.bracket_nodes import build_bracket_graph
from tournaments.models import Tournament


class Command(BaseCommand):
    help = "Print the derived bracket-node graph for a tournament."

    def add_arguments(self, parser):
        parser.add_argument("tournament_slug")

    def handle(self, *args, **options):
        slug = options["tournament_slug"]

        try:
            tournament = Tournament.objects.get(slug=slug)
        except Tournament.DoesNotExist as exc:
            raise CommandError(f"Tournament not found: {slug}") from exc

        graph = build_bracket_graph(tournament)

        self.stdout.write(
            self.style.SUCCESS(
                f"Bracket graph for {tournament}: "
                f"{len(graph.nodes)} input nodes, {len(graph.edges)} advance edges."
            )
        )

        self.stdout.write("\nInput nodes:")
        for node in graph.nodes:
            self.stdout.write(
                f"  {node.node_id:<7} {node.display_label:<10} "
                f"match={node.match_number:<3} side={node.side:<4} "
                f"source={node.source_slot or '-'}"
            )

        self.stdout.write("\nAdvance edges:")
        for edge in graph.edges:
            self.stdout.write(
                f"  M{edge.from_match_number:03d} {edge.outcome:<6} -> {edge.to_node_id}"
            )

        self.stdout.write("\nThird-place group compatibility:")
        for group, nodes in sorted(graph.third_place_nodes_by_group.items()):
            labels = ", ".join(node.node_id for node in nodes)
            self.stdout.write(f"  3{group}: {labels}")
