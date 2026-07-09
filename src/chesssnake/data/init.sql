-- chesssnake schema initialization.
-- Idempotent: safe to run against a fresh or already-initialized database.

-- Games Table
-- The board (plus turn, castling rights, en-passant, and the move clocks) is stored
-- as a single standard FEN string. Status/Draw/Termination/Version are separate.
-- A triple (GroupId, WhiteId, BlackId) can own many games, one per Generation: the
-- current game is the row with the highest Generation; earlier generations are the
-- (read-only) archive of finished games between the same players.
CREATE TABLE IF NOT EXISTS Games (
    GroupId BIGINT NOT NULL,
    WhiteId BIGINT NOT NULL,
    BlackId BIGINT NOT NULL,
    Generation INTEGER NOT NULL DEFAULT 1,
    Fen TEXT NOT NULL,
    Draw INTEGER CHECK (Draw IN (0, 1)) DEFAULT NULL,
    Status INTEGER NOT NULL CHECK (Status BETWEEN 0 AND 3),
    Termination TEXT DEFAULT NULL,
    Version INTEGER NOT NULL DEFAULT 1,
    WName TEXT DEFAULT NULL,
    BName TEXT DEFAULT NULL,
    CreatedAt TIMESTAMP DEFAULT NOW(),
    UpdatedAt TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (GroupId, WhiteId, BlackId, Generation)
);

-- Moves Table: one row per applied move (Ply >= 1), plus a Ply-0 row per game
-- recording the initial position. San is the move played; PositionKey is the first
-- four FEN fields, used for threefold-repetition detection. Scoped per Generation.
CREATE TABLE IF NOT EXISTS Moves (
    GroupId BIGINT NOT NULL,
    WhiteId BIGINT NOT NULL,
    BlackId BIGINT NOT NULL,
    Generation INTEGER NOT NULL DEFAULT 1,
    Ply INTEGER NOT NULL,
    San TEXT DEFAULT NULL,
    PositionKey TEXT NOT NULL,
    PRIMARY KEY (GroupId, WhiteId, BlackId, Generation, Ply)
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

CREATE INDEX IF NOT EXISTS idx_moves_game ON Moves (GroupId, WhiteId, BlackId, Generation);

CREATE INDEX IF NOT EXISTS idx_challenges_group_id ON Challenges (GroupId);
CREATE INDEX IF NOT EXISTS idx_challenges_player_ids ON Challenges (Challenger, Challenged);