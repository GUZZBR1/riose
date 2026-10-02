"""Allow the documented `python -m riose.digital_twin ...` entry point."""

from .cli import main

raise SystemExit(main())
