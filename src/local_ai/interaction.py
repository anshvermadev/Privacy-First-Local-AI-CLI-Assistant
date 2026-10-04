"""Scoped interactive input; terminal UI supplies its own prompt handler."""
from contextvars import ContextVar
import getpass

handler = ContextVar("local_ai_prompt_handler", default=None)


def ask(message, *, password=False):
    callback = handler.get()
    if callback is not None:
        return callback(message, password=password)
    return getpass.getpass(message) if password else input(message)
