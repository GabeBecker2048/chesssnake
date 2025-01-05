-- Challenges Table
CREATE TABLE Challenges (
    GroupId BIGINT NOT NULL,
    Challenger BIGINT NOT NULL,
    Challenged BIGINT NOT NULL,
    CreatedAt TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (GroupId, Challenger, Challenged),
    CONSTRAINT fk_challenges_group FOREIGN KEY (GroupId) REFERENCES Groups(GroupId) ON DELETE CASCADE
);

-- Games Table
CREATE TABLE Games (
    GroupId BIGINT NOT NULL,
    WhiteId BIGINT NOT NULL,
    BlackId BIGINT NOT NULL,
    Board TEXT NOT NULL,
    Turn BOOLEAN NOT NULL,
    PawnMove CHAR(2) CHECK (PawnMove ~ '^[a-h][1-8]$') DEFAULT NULL,
    Draw BOOLEAN DEFAULT NULL,
    Moved CHAR(6) NOT NULL,
    WName TEXT DEFAULT NULL,
    BName TEXT DEFAULT NULL,
    CreatedAt TIMESTAMP DEFAULT NOW(),
    UpdatedAt TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (GroupId, WhiteId, BlackId),
    CONSTRAINT fk_games_group FOREIGN KEY (GroupId) REFERENCES Groups(GroupId) ON DELETE CASCADE
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
CREATE TRIGGER trigger_set_updated_at
BEFORE UPDATE ON Games
FOR EACH ROW
EXECUTE FUNCTION set_games_updated_at();

-- Indexes for improving query performance
CREATE INDEX idx_games ON Games (GroupId, WhiteId, BlackId);
CREATE INDEX idx_games_group_id ON Games (GroupId);
CREATE INDEX idx_games_player_ids ON Games (WhiteId, BlackId);

CREATE INDEX idx_challenges ON Challenges (GroupId, Challenger, Challenged);
CREATE INDEX idx_challenges_group_id ON Challenges (GroupId);
CREATE INDEX idx_challenges_player_ids ON Challenges (WhiteId, BlackId);
