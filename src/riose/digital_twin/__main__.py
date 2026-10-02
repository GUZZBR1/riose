"""Preserve ``python -m riose.digital_twin`` as a compatibility command."""

from riose.products.ear_tag.digital_twin.cli import main

raise SystemExit(main())
