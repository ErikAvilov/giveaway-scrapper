# Giveaway Admin Dashboard

Next.js App Router dashboard for browsing giveaways stored in Neon PostgreSQL.
Runs on your main PC. The Raspberry Pi collector never talks to this app directly.

## Setup

```bash
cd dashboard
cp .env.example .env.local
# Set DATABASE_URL to the Neon *pooled* connection string (same DB as the collector).
# Do NOT use NEXT_PUBLIC_DATABASE_URL.

npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Scripts

```bash
npm run dev       # local development
npm run lint
npx tsc --noEmit  # typecheck
npm run build
npm start
```

## Security notes

- All SQL runs server-side via `postgres` (postgres.js).
- `DATABASE_URL` is server-only (`src/lib/db.ts` imports `server-only`).
- Mutations use Server Actions with parameterized queries.
- No auth yet — intended for localhost use. Query modules are isolated for later auth wrapping.
