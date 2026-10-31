#!/usr/bin/env python3
"""Deny recognized bulk reads before Codex executes them; never execute shell input."""
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys


READ_TOOLS = {'Read', 'read_file', 'read_text_file'}
SHELL_TOOLS = {'Bash', 'exec_command', 'shell', 'shell_command'}
READ_COMMANDS = {'cat', 'head', 'tail', 'less', 'more', 'sed'}


def threshold():
    value = os.environ.get('SHUNT_MIN_LINES', '350')
    return int(value) if value.isascii() and value.isdigit() else 350


def large_file(name, cwd, maximum):
    # Literal paths only. Do not evaluate substitutions or expand shell programs.
    path = Path(name).expanduser()
    if not path.is_absolute():
        path = cwd / path
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        with path.open('rb') as stream:
            for number, _ in enumerate(stream, 1):
                if number > maximum:
                    return str(path)
    except (OSError, ValueError):
        pass  # Let the actual command report missing/unreadable paths.
    return None


def tokenize(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|<>()\n')
    lexer.whitespace = ' \t\r'
    lexer.whitespace_split = True
    lexer.commenters = '#'
    return list(lexer)


def segments(tokens):
    part = []
    for token in tokens:
        if token and all(c in ';&|()\n' for c in token):
            if part:
                yield part
                part = []
        else:
            part.append(token)
    if part:
        yield part


def unwrap(words):
    words = list(words)
    while words and re.match(r'^[A-Za-z_][A-Za-z_0-9]*=', words[0]):
        words.pop(0)
    if words and Path(words[0]).name in {'env', 'command'}:
        words.pop(0)
        while words and (words[0] == '--' or re.match(r'^[A-Za-z_][A-Za-z_0-9]*=', words[0])):
            words.pop(0)
    return words


def read_operands(words):
    """Return literal input paths and a proven line bound (None = unbounded)."""
    name, args = Path(words[0]).name, words[1:]
    paths, expressions = [], []
    bound = 10 if name in {'head', 'tail'} else None
    quiet, positional, stdin = False, False, None
    follow = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('>', '>>'):
            # No content is returned by this direct reader. Pipelines are not
            # exempt, and only stdout redirection without descriptor syntax is.
            if i == 0 or not args[i - 1].isdigit() or args[i - 1] == '1':
                return [], 0
            i += 2; continue
        if arg == '<' and i + 1 < len(args):
            stdin = args[i + 1]; i += 2; continue
        if arg == '--':
            positional = True; i += 1; continue
        if name in {'head', 'tail'} and not positional:
            if arg in ('-n', '--lines', '-c', '--bytes') and i + 1 < len(args):
                value = args[i + 1]
                bound = int(value) if arg in ('-n', '--lines') and value.isdigit() else None
                i += 2; continue
            match = re.fullmatch(r'(?:-n|--lines=)([0-9]+)', arg) or re.fullmatch(r'-([0-9]+)', arg)
            if match:
                bound = int(match[1]); i += 1; continue
            if arg.startswith(('-n', '--lines=', '-c', '--bytes=')):
                bound = None; i += 1; continue
            if name == 'tail' and arg in ('-f', '-F', '--follow'):
                follow = True; i += 1; continue
        if name == 'sed' and not positional:
            if arg in ('-e', '--expression') and i + 1 < len(args):
                expressions.append(args[i + 1]); i += 2; continue
            if arg.startswith('--expression='):
                expressions.append(arg.split('=', 1)[1]); i += 1; continue
            if arg in ('-f', '--file') and i + 1 < len(args):
                expressions.append('unknown-script'); i += 2; continue
            if arg == '--quiet' or arg == '--silent' or re.fullmatch(r'-[nEr]+', arg):
                quiet = quiet or 'n' in arg or arg.startswith('--'); i += 1; continue
        if not positional and arg.startswith('-') and arg != '-':
            i += 1; continue
        if name == 'sed' and not expressions:
            expressions.append(arg)
        elif arg != '-':
            paths.append(arg)
        i += 1
    if stdin is not None:
        paths.append(stdin)
    if name == 'sed' and quiet:
        # Only a simple numeric print range proves a bounded read. `sed '1,5p'`
        # without -n still prints the whole file and must not get this exception.
        if len(expressions) == 1:
            match = re.fullmatch(r'(\d+)(?:,(\d+))?p', expressions[0])
            if match:
                start = int(match[1]); end = int(match[2] or match[1])
                if 0 < start <= end:
                    bound = end - start + 1
    return paths, None if follow else bound


def check_shell(command, cwd, maximum, depth=0):
    if depth > 4:
        return None
    try:
        commands = segments(tokenize(command))
        for words in commands:
            words = unwrap(words)
            if not words:
                continue
            name = Path(words[0]).name
            if name == 'cd' and len(words) == 2:
                candidate = Path(words[1]).expanduser()
                cwd = candidate if candidate.is_absolute() else cwd / candidate
                continue
            if name in {'bash', 'sh', 'zsh'}:
                for index, option in enumerate(words[1:], 1):
                    if option.startswith('-') and 'c' in option and index + 1 < len(words):
                        found = check_shell(words[index + 1], cwd, maximum, depth + 1)
                        if found:
                            return found
                        break
                continue
            if name not in READ_COMMANDS:
                continue
            paths, bound = read_operands(words)
            # A bounded read must also fit across its operands, not per file.
            if bound is not None and bound * len(paths) <= maximum:
                continue
            for path in paths:
                found = large_file(path, cwd, maximum)
                if found:
                    return found
    except ValueError:
        pass  # Malformed shell syntax belongs to the shell, not this policy.
    return None


def inspect(payload):
    if payload.get('hook_event_name') != 'PreToolUse':
        return None
    tool = payload.get('tool_name', '')
    data = payload.get('tool_input', {})
    if not isinstance(data, dict):
        return None
    maximum = threshold()
    cwd = Path(payload.get('cwd') or os.getcwd())
    workdir = data.get('workdir') or data.get('cwd')
    if isinstance(workdir, str):
        cwd = Path(workdir) if Path(workdir).is_absolute() else cwd / workdir
    if tool in SHELL_TOOLS:
        command = data.get('command', data.get('cmd', ''))
        if isinstance(command, list) and all(isinstance(v, str) for v in command):
            command = shlex.join(command)
        return check_shell(command, cwd, maximum) if isinstance(command, str) else None
    if tool in READ_TOOLS:
        limit = data.get('limit')
        # An offset alone is not an output limit.
        if isinstance(limit, int) and not isinstance(limit, bool) and 0 < limit <= maximum:
            return None
        path = data.get('file_path', data.get('path'))
        return large_file(path, cwd, maximum) if isinstance(path, str) else None
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        found = inspect(payload) if isinstance(payload, dict) else None
    except (ValueError, OSError):
        found = None
    if not found:
        print('{}')  # Do not override the host's normal permission policy.
        return
    worker = Path(__file__).resolve().parents[1] / 'scripts/bulk-read'
    reason = (f'Shunt blocked a bulk read of {found} (over {threshold()} lines). '
              f'Use {shlex.quote(str(worker))} --backend codex --question "<focused question>" '
              f'--paths {shlex.quote(found)}. For exact editing context, use a bounded '
              f'head/tail or sed -n range of at most {threshold()} lines. '
              'Do not bypass this by changing readers or splitting a whole-file dump.')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                      'permissionDecision': 'deny', 'permissionDecisionReason': reason}}))


if __name__ == '__main__':
    main()
