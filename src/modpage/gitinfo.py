"""Read the repo's tags and history, for generators that pull from the git tree.

Plumbing only -- ``git`` is called as a subprocess with machine-readable
formats, so there is no dependency to install and no object database to parse.
A repo without git (an exported tarball, a fresh ``init`` with no commits) is
not an error here: :attr:`GitRepo.available` is false and every accessor
returns nothing, so a page still builds, just without its history.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

# Record/field separators. Both are control characters git will never emit in a
# subject or body, so a multi-line commit message survives the split intact.
RS = "\x1e"
FS = "\x1f"

# `feat(scope)!: subject` -- the Conventional Commits shape, used to group
# commits into changelog headings. Anything that does not match keeps its whole
# subject and gets no type.
_CONVENTIONAL = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?:[ \t]*(?P<subject>.+)$",
    re.IGNORECASE,
)
_VERSION_PREFIX = re.compile(r"^(?:v|ver|version|release|rel)[-_./]?(?=\d)", re.IGNORECASE)
_PRERELEASE = re.compile(r"[-+](?:alpha|beta|rc|pre|dev|snapshot)", re.IGNORECASE)
_NUMBERS = re.compile(r"\d+|\D+")


def strip_version_prefix(name: str) -> str:
    """``v1.2.0`` / ``release-1.2.0`` -> ``1.2.0``; anything else is untouched."""
    return _VERSION_PREFIX.sub("", str(name))


def version_key(value: str) -> tuple:
    """Sort ``1.10.0`` after ``1.9.0``, and a prerelease before its release."""
    text = strip_version_prefix(value)
    parts: list[Any] = []
    for chunk in _NUMBERS.findall(text):
        parts.append((0, int(chunk), "") if chunk.isdigit() else (1, 0, chunk.lower()))
    return (tuple(parts), text)


@dataclass
class Commit:
    hash: str
    short: str
    author: str
    email: str
    date: str          # YYYY-MM-DD
    datetime: str      # full ISO 8601, for ordering within a day
    subject: str       # the raw first line
    body: str
    #: Conventional-commit fields; ``type`` is ``None`` for a plain subject.
    type: str | None = None
    scope: str | None = None
    breaking: bool = False
    #: The subject with any ``type(scope):`` prefix removed, sentence-cased.
    title: str = ""

    def as_element(self) -> dict[str, Any]:
        return {
            "hash": self.hash, "short": self.short, "author": self.author,
            "email": self.email, "date": self.date, "datetime": self.datetime,
            "subject": self.subject, "body": self.body, "type": self.type,
            "scope": self.scope, "breaking": self.breaking, "title": self.title,
        }


@dataclass
class Tag:
    name: str
    version: str
    date: str
    datetime: str
    subject: str
    body: str
    commit: str
    prerelease: bool = False
    commits: list[Commit] = field(default_factory=list)

    def as_element(self) -> dict[str, Any]:
        return {
            "tag": self.name, "version": self.version, "date": self.date,
            "datetime": self.datetime, "subject": self.subject, "body": self.body,
            "commit": self.commit, "prerelease": self.prerelease,
        }


def _title_from(subject: str, type_: str | None) -> str:
    text = subject.strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _parse_subject(subject: str) -> tuple[str | None, str | None, bool, str]:
    match = _CONVENTIONAL.match(subject.strip())
    if not match:
        return None, None, subject.strip().endswith("!"), _title_from(subject, None)
    type_ = match.group("type").lower()
    return (
        type_,
        match.group("scope") or None,
        bool(match.group("breaking")),
        _title_from(match.group("subject"), type_),
    )


class GitRepo:
    """A thin, lazy reader over one repository."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._checked = False
        self._available = False
        self._cache: dict[tuple, Any] = {}

    # -- plumbing ---------------------------------------------------------

    def _run(self, *args: str) -> str | None:
        """Run one git command; ``None`` when git or the repo is unusable."""
        if shutil.which("git") is None:
            return None
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    @property
    def available(self) -> bool:
        if not self._checked:
            self._checked = True
            self._available = self._run("rev-parse", "--git-dir") is not None
        return self._available

    def unavailable_reason(self) -> str:
        if shutil.which("git") is None:
            return "git is not on PATH"
        return f"{self.root} is not inside a git work tree (or it has no commits yet)"

    # -- history ----------------------------------------------------------

    def tags(self, match: str | None = None, *, sort: str = "date") -> list[Tag]:
        """Every tag, newest first. ``match`` is a glob such as ``v*``."""
        key = ("tags",)
        if key not in self._cache:
            fmt = FS.join([
                "%(refname:short)", "%(creatordate:iso-strict)",
                "%(contents:subject)", "%(contents:body)",
                # An annotated tag's own object is not the commit it points at;
                # `*objectname` peels to the commit, and is empty for a
                # lightweight tag, where `objectname` is already the commit.
                "%(objectname)", "%(*objectname)",
            ]) + RS
            out = self._run("for-each-ref", "--sort=-creatordate", f"--format={fmt}",
                            "refs/tags") if self.available else None
            tags: list[Tag] = []
            for record in (out or "").split(RS):
                record = record.strip("\n")
                if not record:
                    continue
                fields = record.split(FS)
                if len(fields) < 6:
                    continue
                name, iso, subject, body, obj, peeled = fields[:6]
                tags.append(Tag(
                    name=name,
                    version=strip_version_prefix(name),
                    date=iso[:10],
                    datetime=iso,
                    subject=subject.strip(),
                    body=body.strip(),
                    commit=peeled or obj,
                    prerelease=bool(_PRERELEASE.search(name)),
                ))
            self._cache[key] = tags

        tags = list(self._cache[key])
        if match:
            tags = [tag for tag in tags if fnmatch(tag.name, match)]
        if sort == "version":
            tags.sort(key=lambda tag: version_key(tag.version), reverse=True)
        return tags

    def commits(self, *, since: str | None = None, until: str | None = None,
                paths: list[str] | None = None, limit: int | None = None,
                no_merges: bool = True) -> list[Commit]:
        """Commits in ``since..until``; both ends optional, newest first."""
        if not self.available:
            return []
        fmt = FS.join(["%H", "%h", "%an", "%ae", "%aI", "%s", "%b"]) + RS
        args = ["log", f"--format={fmt}"]
        if no_merges:
            args.append("--no-merges")
        if limit:
            args.append(f"-n{int(limit)}")
        if since and until:
            args.append(f"{since}..{until}")
        elif since:
            args.append(f"{since}..HEAD")
        elif until:
            args.append(until)
        if paths:
            args.append("--")
            args.extend(paths)

        out = self._run(*args)
        commits: list[Commit] = []
        for record in (out or "").split(RS):
            record = record.strip("\n")
            if not record:
                continue
            fields = record.split(FS)
            if len(fields) < 7:
                continue
            hash_, short, author, email, iso, subject, body = fields[:7]
            type_, scope, breaking, title = _parse_subject(subject)
            body = body.strip()
            commits.append(Commit(
                hash=hash_, short=short, author=author, email=email,
                date=iso[:10], datetime=iso, subject=subject.strip(), body=body,
                type=type_, scope=scope,
                # `BREAKING CHANGE:` in the body counts too, per the spec.
                breaking=breaking or "BREAKING CHANGE" in body,
                title=title,
            ))
        return commits

    def remote_url(self) -> str | None:
        """``origin`` as a browsable https URL, or ``None``."""
        raw = (self._run("remote", "get-url", "origin") or "").strip()
        if not raw:
            return None
        if raw.startswith("git@"):  # git@github.com:user/repo.git
            host, _, path = raw[4:].partition(":")
            raw = f"https://{host}/{path}"
        return raw.removesuffix(".git").rstrip("/")

    def file_dates(self, relative: str) -> tuple[str | None, str | None]:
        """``(first commit date, last commit date)`` for one path."""
        out = self._run("log", "--format=%aI", "--", relative)
        lines = [line for line in (out or "").splitlines() if line]
        if not lines:
            return None, None
        return lines[-1][:10], lines[0][:10]
