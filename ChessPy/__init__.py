import importlib.metadata

def check_optional_dependency(dependency):
    try:
        importlib.metadata.version(dependency)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False

if check_optional_dependency("psycopg2") or check_optional_dependency("psycopg2-binary"):
    from .postgres.Game import Game
else:
    from .chesslib.Game import Game

__all__ = ['Game']
