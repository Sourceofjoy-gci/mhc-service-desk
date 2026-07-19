-- =============================================================================
-- MHC e-Ticketing — initial database extensions and roles
-- Loaded automatically on first Postgres startup.
-- =============================================================================

-- Required for trigram matching used by ticket/contact dedup
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Used by full-text search across ticket content
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Cryptographic functions for token hashing and signed URLs
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- UUID generation as a backup to client-side uuid generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
