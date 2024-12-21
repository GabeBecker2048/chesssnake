try:
    import psycopg2
    from .postgres.Game import Game
except ImportError:
    from .chesslib.Game import Game

__all__ = ['Game']
