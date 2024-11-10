CREATE TABLE Challenges (
    GuildId BIGINT NOT NULL,
    Challenger BIGINT NOT NULL,
    Challenged BIGINT NOT NULL
);

CREATE TABLE Games (
    GuildId BIGINT NOT NULL,
    WhiteId BIGINT NOT NULL,
    BlackId BIGINT NOT NULL,
    Board VARCHAR NOT NULL,
    Turn BIT(1) NOT NULL,
    PawnMove VARCHAR(2),
    Draw BIT(1),
    Moved BIT(6) NOT NULL,
    WName VARCHAR,
    BNname VARCHAR
);
