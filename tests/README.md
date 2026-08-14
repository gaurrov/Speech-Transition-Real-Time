# tests/ (root level)

Reserved for cross-cutting integration tests that exercise the frontend and
backend together (e.g. a Playwright test that drives the UI against a running
backend). Component-level tests live alongside the code they test:

- Backend unit/integration tests: `backend/tests/`
- Frontend unit tests: colocate with components under `frontend/src/` once
  a frontend test runner (e.g. Vitest) is added — not yet configured.
