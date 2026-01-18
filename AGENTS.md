# Repository Guidelines

## Project Structure & Module Organization
- `frontend/` is a Next.js 16 + React 19 admin UI. Page entry is `frontend/app/page.tsx`, with UI views in `frontend/components/` and shared UI primitives in `frontend/components/ui/`.
- `frontend/app/api/**/route.ts` contains Next.js API routes that proxy requests to the Flask backend.
- `backend/` is a Flask API plus a Discord self-bot and AI tooling. Key entry points: `backend/app.py` (API) and `backend/bot.py` (bot).
- `backend/scripts/` holds operational scripts such as `create_admin.py` and `clear_database.py`.
- Runtime data lives under `backend/data/` (SQLite DB, FAISS index, scraped images, logs).

## Build, Test, and Development Commands
Run commands from the relevant subdirectory.

Frontend:
- `pnpm install` — install dependencies.
- `pnpm dev` — start the Next.js dev server on port 3000.
- `pnpm build` — production build.
- `pnpm lint` — run ESLint checks.

Backend:
- `pip install -r requirements.txt` — install Python dependencies.
- `python app.py` — start the Flask API on port 5001.
- `python bot.py` — start the Discord bot.
- `python scripts/create_admin.py` — create an admin user.
- `python scripts/clear_database.py` — clear the SQLite database.

## Coding Style & Naming Conventions
- Frontend: TypeScript/React in `frontend/`, two-space indentation, no semicolons in most files; follow existing file style and keep UI components in `components/`.
- Backend: Python in `backend/`, follow PEP 8 (4-space indentation). Keep business logic in modules like `database.py` and `vector_engine.py`.
- API routes should remain thin proxies; place backend logic in Flask endpoints instead of Next.js API handlers.

## Testing Guidelines
- No dedicated test suite is configured in this repo. If you add tests, keep them close to the code (for example, `frontend/__tests__/` or `backend/tests/`) and document how to run them in your PR.

## Commit & Pull Request Guidelines
- Git history shows short, generic messages (e.g., “update”); no strict convention is enforced. Prefer concise, imperative summaries ("Add shop filters", "Fix bot status polling").
- PRs should include: a clear description, steps to validate (commands or manual steps), and screenshots for UI changes.

## Security & Configuration Tips
- Environment variables are loaded via `python-dotenv` in the backend (`backend/config.py`).
- The frontend relies on `NEXT_PUBLIC_BACKEND_URL` to reach the Flask API; ensure it matches the backend host/port in local development.
