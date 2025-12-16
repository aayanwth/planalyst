-- =============================================================
-- PLanalyst — Database Initialization Script
-- =============================================================
-- Runs automatically on first container start via
-- docker-entrypoint-initdb.d/
-- =============================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create medallion architecture schemas
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS training;

-- Grant usage on all schemas to the default user
GRANT ALL ON SCHEMA bronze TO planalyst;
GRANT ALL ON SCHEMA silver TO planalyst;
GRANT ALL ON SCHEMA gold TO planalyst;
GRANT ALL ON SCHEMA training TO planalyst;

-- Verify setup
DO $$
BEGIN
    RAISE NOTICE 'PLanalyst database initialized successfully!';
    RAISE NOTICE 'Schemas: bronze, silver, gold, training';
    RAISE NOTICE 'Extension: pgvector enabled';
END $$;
