-- chesssnake schema initialization.
-- Idempotent: safe to run against a fresh or already-initialized database.

-- Games Table
CREATE TABLE IF NOT EXISTS Games (
    GroupId BIGINT NOT NULL,
    WhiteId BIGINT NOT NULL,
    BlackId BIGINT NOT NULL,
    Board TEXT NOT NULL,
    Turn INTEGER NOT NULL CHECK (Turn IN (0, 1)),
    PawnMove CHAR(2) CHECK (PawnMove ~ '^[a-h][1-8]$') DEFAULT NULL,
    Draw INTEGER CHECK (Draw IN (0, 1)) DEFAULT NULL,
    Moved CHAR(6) NOT NULL,
    Status INTEGER NOT NULL CHECK (Status BETWEEN 0 AND 4),
    WName TEXT DEFAULT NULL,
    BName TEXT DEFAULT NULL,
    CreatedAt TIMESTAMP DEFAULT NOW(),
    UpdatedAt TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (GroupId, WhiteId, BlackId)
);

-- Challenges Table
CREATE TABLE IF NOT EXISTS Challenges (
    GroupId BIGINT NOT NULL,
    Challenger BIGINT NOT NULL,
    Challenged BIGINT NOT NULL,
    CreatedAt TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (GroupId, Challenger, Challenged)
);

-- Trigger function to automatically update the UpdatedAt field on row updates
CREATE OR REPLACE FUNCTION set_games_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.UpdatedAt = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to invoke the function before any update on the Games table
DROP TRIGGER IF EXISTS trigger_set_updated_at ON Games;
CREATE TRIGGER trigger_set_updated_at
BEFORE UPDATE ON Games
FOR EACH ROW
EXECUTE FUNCTION set_games_updated_at();

-- Indexes for improving query performance.
-- (The composite PRIMARY KEYs already index the full key tuples, so we only add
--  the partial-key indexes that the primary keys do not cover.)
CREATE INDEX IF NOT EXISTS idx_games_group_id ON Games (GroupId);
CREATE INDEX IF NOT EXISTS idx_games_player_ids ON Games (WhiteId, BlackId);

CREATE INDEX IF NOT EXISTS idx_challenges_group_id ON Challenges (GroupId);
CREATE INDEX IF NOT EXISTS idx_challenges_player_ids ON Challenges (Challenger, Challenged);