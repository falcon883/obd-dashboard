## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## Checks

- [ ] `ruff check .`, `ruff format --check .`, `mypy` and `pytest` pass
- [ ] If I changed `frontend/`: `npm run lint`, `npm test` and `npm run build` pass, and the rebuilt `static/` files are included
- [ ] Tests added or updated (the fake car in `tests/fakes.py` is enough, no hardware needed)
- [ ] Nothing writes to the car, and no full VIN or private data ends up in shared output
