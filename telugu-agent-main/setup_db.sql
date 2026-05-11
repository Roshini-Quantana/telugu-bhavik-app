-- Creates user + db for telugu-bhavik-app. Safe to re-run.
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'roshini') THEN
      CREATE ROLE roshini LOGIN PASSWORD 'gvquRXTLQ9ljGa58';
   ELSE
      ALTER ROLE roshini WITH LOGIN PASSWORD 'gvquRXTLQ9ljGa58';
   END IF;
END
$$;

SELECT 'CREATE DATABASE telugu_bhavik OWNER roshini'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'telugu_bhavik')\gexec

GRANT ALL PRIVILEGES ON DATABASE telugu_bhavik TO roshini;

-- Ensure permissions on public schema (required for PG 15+)
\c telugu_bhavik
GRANT ALL ON SCHEMA public TO roshini;
ALTER ROLE roshini SET search_path TO public, "$user";
