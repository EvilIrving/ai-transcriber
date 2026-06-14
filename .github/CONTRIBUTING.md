# Contributing to AI Transcriber

Thanks for your interest in contributing! Here's how to get started.

## Bug Reports

Found a bug? Open an issue using the **Bug Report** template. Include:

- Steps to reproduce
- Expected vs actual behavior
- Your environment (OS, Python version, browser)
- Any error messages or logs

## Feature Requests

Have an idea? Open a **Feature Request** issue. Describe:

- The problem you're trying to solve
- How the feature would work
- Why it belongs in the core project vs a plugin

## Development Setup

```bash
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber

# Backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && pnpm install
```

### Dev mode

```bash
# From project root
pnpm dev
# API at :8000, Web at :5173 (proxies /api to :8000)
```

See [README.md](README.md) and [AGENTS.md](../AGENTS.md) for full environment setup and architecture overview.

## Code Style

### Backend (Python)
- Flat modules, one concern per file
- Verb-first `snake_case` functions
- Module-private helpers prefixed `_`
- Follow the patterns in `AGENTS.md`

### Frontend (TypeScript)
- `PascalCase` components, `camelCase` functions, `useXxx` hooks
- UI copy goes in `i18n/dictionaries.ts` (all 4 languages)

## Testing

No formal test suite yet. Smoke tests before opening a PR:

```bash
# Backend import check
cd backend && python -c "import main; print('OK')"

# Frontend typecheck + build
cd frontend && pnpm lint && pnpm build
```

## Pull Request Process

1. Fork the repo and create a feature branch: `git checkout -b feature/your-feature`
2. Make your changes, following existing code patterns
3. Test your changes with the smoke tests above
4. Open a PR against `main` with a clear description
5. Link any related issues

## Questions?

Open a [Discussion](https://github.com/EvilIrving/ai-transcriber/discussions) for questions, ideas, and anything that isn't a bug report or feature request.
