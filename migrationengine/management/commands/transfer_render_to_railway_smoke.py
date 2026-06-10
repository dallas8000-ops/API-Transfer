from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run transfer preflight + transfer + verify + readiness report in one smoke workflow."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            action="append",
            help="Service name or Render service id to process; repeat or pass comma-separated values.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of Render services to inspect.",
        )
        parser.add_argument(
            "--prefix",
            default="",
            help="Optional prefix for Railway service names (example: migrated-).",
        )
        parser.add_argument(
            "--verify-timeout",
            type=int,
            default=300,
            help="Seconds to wait per service for terminal Railway deployment status.",
        )
        parser.add_argument(
            "--verify-interval",
            type=int,
            default=10,
            help="Polling interval in seconds for Railway deployment verification.",
        )
        parser.add_argument(
            "--include-green",
            action="store_true",
            help="Disable failed-only filtering and include services that are already green.",
        )

    def handle(self, *args, **options):
        call_command(
            "transfer_render_to_railway",
            mode="queue",
            only=options.get("only") or [],
            limit=options["limit"],
            prefix=options["prefix"],
            verify_timeout=options["verify_timeout"],
            verify_interval=options["verify_interval"],
            redeploy_existing=True,
            smoke=True,
            include_green=bool(options.get("include_green")),
        )
