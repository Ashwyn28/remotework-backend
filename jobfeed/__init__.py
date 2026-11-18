"""orbbits job's core, free of any web framework.

- `sources`: read open roles from companies' public careers-site APIs.
- `classify`: place a role on the board (UK or not, type of work, level, arrangement).
- `logos`: find a company's logo on its own website.

Used by the daily sync Lambda and by the local Django admin tools.
"""
