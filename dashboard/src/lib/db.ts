import "server-only";

import postgres from "postgres";

/**
 * Server-only Neon connection.
 * Import this module only from Server Components, Route Handlers, or Server Actions.
 * Auth middleware can wrap callers later without changing query code.
 */
const globalForDb = globalThis as unknown as {
  __giveawaySql?: ReturnType<typeof postgres>;
};

function createClient() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error(
      "DATABASE_URL is not set. Copy dashboard/.env.example to .env.local and use the Neon pooled URL.",
    );
  }
  return postgres(url, {
    ssl: "require",
    max: 5,
    idle_timeout: 20,
    connect_timeout: 15,
    prepare: false, // Neon pooler friendly
  });
}

export const sql = globalForDb.__giveawaySql ?? createClient();

if (process.env.NODE_ENV !== "production") {
  globalForDb.__giveawaySql = sql;
}

export type Sql = typeof sql;
