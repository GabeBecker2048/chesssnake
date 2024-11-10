class GameError(Exception):
    def __init__(self, msg):
        super().__init__(msg)


class ChallengeError(GameError):
    def __init__(self, msg):
        super().__init__(msg)
