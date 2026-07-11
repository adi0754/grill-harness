#!/usr/bin/env python3
"""Credential-minimal subprocess environments and persisted evidence sanitization."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Mapping


ALLOWED_SOURCE_VARIABLES = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def minimal_environment(
    source: Mapping[str, str],
    *,
    home: str,
    temp_dir: str,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = {
        name: source[name]
        for name in ALLOWED_SOURCE_VARIABLES
        if source.get(name)
    }
    environment.setdefault("PATH", "/usr/bin:/bin")
    environment["HOME"] = home
    environment["TMPDIR"] = temp_dir
    if extra:
        environment.update({name: str(value) for name, value in extra.items()})
    return environment


def sanitize_runtime_text(text: str, *, temp_root: str | None = None) -> str:
    if temp_root:
        text = text.replace(temp_root, "<TEMP_ROOT>")
        if temp_root.startswith("/var/"):
            text = text.replace("/private" + temp_root, "<TEMP_ROOT>")
    text = re.sub(
        r'("thread_id"\s*:\s*")[^"]+(" )?',
        lambda match: match.group(1) + "<THREAD_ID>" + (match.group(2) or ""),
        text,
    )
    text = re.sub(
        r"(?i)(\bthread[_ -]?id\b\s*[=:]\s*[\"']?)[A-Za-z0-9_-]+",
        r"\1<THREAD_ID>",
        text,
    )
    text = re.sub(
        r'("session_id"\s*:\s*")[^"]+(" )?',
        lambda match: match.group(1) + "<SESSION_ID>" + (match.group(2) or ""),
        text,
    )
    text = re.sub(
        r"(?i)(\bsession[_ -]?id\b\s*[=:]\s*[\"']?)[A-Za-z0-9_-]+",
        r"\1<SESSION_ID>",
        text,
    )
    text = re.sub(
        r"(?i)(\brequest[ _-]?id\b\s*[:=]\s*[\"']?)(?:req_)?[A-Za-z0-9_-]+",
        r"\1<REQUEST_ID>",
        text,
    )
    text = re.sub(r"\breq_[A-Za-z0-9]+\b", "<REQUEST_ID>", text)
    text = re.sub(
        r"(?i)(\bcf-ray\b\s*[:=]\s*[\"']?)[A-Za-z0-9-]+",
        r"\1<CF_RAY>",
        text,
    )
    text = re.sub(
        r"(?i)(\b(?:OPENAI_[A-Z_]*(?:KEY|TOKEN)|ANTHROPIC_[A-Z_]*(?:KEY|TOKEN)|"
        r"CLAUDE_[A-Z_]*(?:KEY|TOKEN)|AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)|"
        r"BEDROCK_[A-Z_]*(?:KEY|TOKEN)|GOOGLE_APPLICATION_CREDENTIALS|"
        r"VERTEX_[A-Z_]+|AZURE_[A-Z_]*(?:KEY|TOKEN))\b\s*[:=]\s*[\"']?)[^\s,\"'}]+",
        r"\1<REDACTED>",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "<REDACTED>", text)
    text = UUID_PATTERN.sub("<UUID>", text)
    return text


def _parse_assignments(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected NAME=VALUE: {value}")
        name, assigned = value.split("=", 1)
        result[name] = assigned
    return result


def _environment_from_args(args: argparse.Namespace) -> dict[str, str]:
    return minimal_environment(
        os.environ,
        home=args.home,
        temp_dir=args.temp_dir,
        extra=_parse_assignments(args.set),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("env-json", "exec-env"):
        command = subparsers.add_parser(name)
        command.add_argument("--home", required=True)
        command.add_argument("--temp-dir", required=True)
        command.add_argument("--set", action="append", default=[])
        if name == "exec-env":
            command.add_argument("remainder", nargs=argparse.REMAINDER)
    sanitize = subparsers.add_parser("sanitize-file")
    sanitize.add_argument("--temp-root")
    sanitize.add_argument("paths", nargs="+")
    args = parser.parse_args()

    if args.command == "env-json":
        print(json.dumps(_environment_from_args(args), sort_keys=True))
        return 0
    if args.command == "exec-env":
        command = args.remainder
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("exec-env requires a command after --")
        os.execvpe(command[0], command, _environment_from_args(args))
    if args.command == "sanitize-file":
        for value in args.paths:
            path = Path(value)
            sanitized = sanitize_runtime_text(
                path.read_text(encoding="utf-8", errors="replace"),
                temp_root=args.temp_root,
            )
            path.write_text(sanitized, encoding="utf-8")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
