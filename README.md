# aws-study

An AWS Solutions Architect exam quiz app with Claude-powered explanations.

Pick a question count, answer multiple-choice questions sampled from a CSV of real exam questions, and ask Claude to explain why an answer is right or wrong — with a "Keywords to watch for" hint and an "Exam tip" at the end of each explanation. Quiz history is saved so you can track scores over time.

Ships in two flavors that share the same question data:
- **Flask app** (`app.py`) for local development — quiz history is persisted to `quiz_history.json`.
- **Cloudflare Worker** (`worker.js` + `wrangler.toml`) for production — quiz history lives in a KV namespace.

## Quick start (local)

```bash
pip install flask flask-limiter pandas anthropic python-dotenv
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
python app.py        # http://localhost:5000
```

## Quick start (Cloudflare Worker)

```bash
npm install
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler dev      # local emulator
npm run deploy        # ship to Cloudflare
```

The Worker reads questions from a baked-in `questions.json` (generated from `study.csv`); the Flask app reads `study.csv` at startup.

## Runtime Workflow

```
USER
  │
  ▼
GET /                 ────►  render quiz UI (templates/index.html)
GET /api/questions    ────►  sample N random questions from study.csv
                             return: question, choices, answer, num_answers
  │
  ▼
USER picks answers, submits
  │
  ▼
POST /api/history/save  ──►  append {date, score, total, %, duration, questions}
                             to quiz_history.json (or KV in the Worker)
  │
  ▼
POST /api/explain       ──►  Claude (claude-opus-4-6) streams an SSE response:
                             1. Why correct is right / user's answer is wrong
                             2. Keywords to watch for
                             3. Exam tip
                             Follow-up questions reuse the message history
                             so it's a multi-turn conversation per question.

GET /api/history        ──►  full history JSON for the stats screen
```

**Rate limits** (Flask side, via `flask-limiter`):
- Global: 200 req/day, 50 req/hour per IP
- `/api/explain` (the Claude-burning one): 30/hour, 100/day per IP

The Worker side trusts Cloudflare's built-in protections instead of running `flask-limiter`.

## Build & Deploy Pipeline

```
study.csv  (master question source, edited by hand)
   │
   ├─► Flask app reads it directly at startup (pandas.read_csv)
   │
   └─► questions.json is generated for the Worker bundle
         │
         ▼
   wrangler deploy   →  Cloudflare Worker
                        ├─ serves /public/ static assets
                        ├─ runs worker.js for /api/* routes
                        └─ reads/writes HISTORY KV namespace
                          (binding id: f910c3e1...)
```

`wrangler.toml` pins:
- `name = "aws-study"`
- `compatibility_date = "2025-01-01"`
- `[assets] directory = "./public"`
- `[[kv_namespaces]] binding = "HISTORY"` for quiz history persistence

## CI

`.github/workflows/ci.yml` runs on every push and PR:

1. **Python compile-check** — `python -m compileall app.py quiz.py` catches syntax errors before they hit the running Flask process.
2. **Ruff lint** — `ruff check` restricted to the must-pass set (`E9`, `F63`, `F7`, `F82`) — syntax, undefined names, structural bugs. No style noise.
3. **Wrangler dry-run** — `npx wrangler deploy --dry-run` validates `wrangler.toml`, the Worker bundle, and KV bindings without actually deploying.

No deploy step in CI — `npm run deploy` stays manual so production pushes are deliberate. The Anthropic API key is set as a Wrangler secret on the production environment and never touches the repo.

## File map

| File | Role |
|---|---|
| `app.py` | Flask server: question sampling, history, Claude streaming via `anthropic` SDK |
| `worker.js` | Cloudflare Worker version of the same API, using `fetch` against the Anthropic API directly |
| `quiz.py` | CLI tool for terminal-only quiz runs |
| `study.csv` | Master question bank (Flask reads this at startup) |
| `questions.json` | Generated question data baked into the Worker bundle |
| `templates/` | Jinja templates (Flask) |
| `public/` | Static assets served by the Worker |
| `wrangler.toml` | Cloudflare Worker config + KV binding |
| `.env` | Local-only secrets — `ANTHROPIC_API_KEY` (gitignored) |
| `quiz_history.json` | Local quiz history (gitignored) |

## License

MIT
