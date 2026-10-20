"""Allow `python -m jobs` as an alias for the replenishment job."""

from jobs.run_replenishment import main

raise SystemExit(main())
