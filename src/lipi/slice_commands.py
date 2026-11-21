"""Command hints for title and document text searches."""
import os
import re
from shlex import quote
from urllib.parse import unquote


# @trace docs/ru/slice-output.md#repo-search,docs/ru/slice-search.md#command
def is_title_query(query):
    path = unquote(query)
    return (bool(query.strip()) and path not in ('.', '..')
            and not any(separator in path for separator in ('#', '/', '\\'))
            and not re.fullmatch(r'\S+\.[a-zA-Z][\w-]*', path))


# @trace docs/ru/slice-output.md#repo-search,docs/ru/slice-search.md#command
def slice_command(target, *, search=False):
    command = 'lipi slice '
    if search:
        if target.startswith('-'):
            target = '--search=' + target
        else:
            command += '--search '
    elif target.startswith('-'):
        command += '-- '
    if os.name == 'nt':
        # PowerShell распознаёт и типографские одинарные кавычки.
        quoted = "'%s'" % re.sub(r"['‘’‚‛]", r'\g<0>\g<0>', target)
    else:
        quoted = quote(target)
    return command + quoted
