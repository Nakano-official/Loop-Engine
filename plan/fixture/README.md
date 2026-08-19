# The fixture plan

Not the project. This is the three-step plan (`normalize` -> `tokenize` ->
`token_counts`) that was used to build and prove the runner: contract hand-off
between steps, RED_GATE R1..R5, FREEZE, `run --all`, the escalation cap, and the
planner's proposal guard were all first exercised against it.

All three steps went green on the real sandbox. It is kept because it is the
only plan whose expected behaviour is fully known, which makes it the thing to
re-run when the runner changes.

The live plan is no longer seeded from this repository. It is generated inside
the distro by `plan bootstrap` from the requirements the human writes, and lives
at `/srv/loop/project/plan/`. The working tree that produced this fixture is
archived in the distro at `/srv/loop/project.fixture`.

Note it predates linter rule L12: `files_write` here is `src/*.py` at the top of
`src/`, which is still valid, but the imports use the old `from src.x import y`
form from before `conftest.py` put `src/` on `sys.path`.
