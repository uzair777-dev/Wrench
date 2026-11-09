"""Storage and local data store package."""


def get_connection(*args, **kwargs):
    from . import db

    return db.get_connection(*args, **kwargs)


__all__ = ["get_connection"]
