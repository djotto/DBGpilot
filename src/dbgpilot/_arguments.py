"""Compatibility aliases for renamed Python keyword arguments."""

from functools import wraps


def normalize_arguments(method, parameters):
    """Translate legacy keywords, rejecting duplicate old and new arguments."""
    parameters = dict(parameters)
    for alias, name in getattr(method, "keyword_aliases", {}).items():
        if alias in parameters:
            if name in parameters:
                raise TypeError(f"Specify only one of {alias!r} and {name!r}")
            parameters[name] = parameters.pop(alias)
    return parameters


def keyword_aliases(**aliases):
    """Keep legacy keywords callable while exposing descriptive parameter names."""
    def decorate(method):
        @wraps(method)
        async def wrapped(*args, **kwargs):
            return await method(*args, **normalize_arguments(wrapped, kwargs))

        wrapped.keyword_aliases = aliases
        return wrapped

    return decorate
