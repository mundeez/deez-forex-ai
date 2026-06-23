-- Add verifier_confidence to ai_decisions table
-- Run: docker compose exec -T postgres psql -U forex -d deez_forex -f /app/migrate_verifier_confidence.sql

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ai_decisions' AND column_name = 'verifier_confidence'
    ) THEN
        ALTER TABLE ai_decisions ADD COLUMN verifier_confidence FLOAT;
    END IF;
END $$;
