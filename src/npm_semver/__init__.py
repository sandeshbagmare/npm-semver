"""Semantic version ranges for Python.

``semver`` compares versions and ``packaging`` parses them, but neither answers
the question npm users ask every day: does ``1.4.2`` satisfy ``^1.2.0``?

    >>> from npm_semver import satisfies, max_satisfying
    >>> satisfies("1.4.2", "^1.2.0")
    True
    >>> max_satisfying(["1.2.0", "1.4.2", "2.0.0"], "^1.2.0")
    Version(major=1, minor=4, patch=2, prerelease=(), build='')
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace

__all__ = [
    "InvalidRange",
    "InvalidVersion",
    "Version",
    "filter_satisfying",
    "max_satisfying",
    "min_satisfying",
    "parse",
    "parse_range",
    "satisfies",
    "sort_versions",
]

__version__ = "0.1.0"


class InvalidVersion(ValueError):
    """Raised when a version string is not a semantic version."""


class InvalidRange(ValueError):
    """Raised when a range string cannot be parsed."""


_VERSION_RE = re.compile(
    r"""
    ^
    v?(?P<major>\d+)
    (?:\.(?P<minor>\d+))?
    (?:\.(?P<patch>\d+))?
    (?:-(?P<prerelease>[0-9A-Za-z.-]+))?
    (?:\+(?P<build>[0-9A-Za-z.-]+))?
    $
    """,
    re.VERBOSE,
)


@dataclass(frozen=True, order=False)
class Version:
    """A parsed version. Missing components of a partial version are ``None``."""

    major: int
    minor: int | None = None
    patch: int | None = None
    prerelease: tuple[str, ...] = ()
    build: str = ""

    def __str__(self) -> str:
        text = str(self.major)
        if self.minor is not None:
            text += f".{self.minor}"
        if self.patch is not None:
            text += f".{self.patch}"
        if self.prerelease:
            text += "-" + ".".join(self.prerelease)
        if self.build:
            text += "+" + self.build
        return text

    def __repr__(self) -> str:
        return (
            f"Version(major={self.major}, minor={self.minor}, patch={self.patch}, "
            f"prerelease={self.prerelease!r}, build={self.build!r})"
        )

    @property
    def is_partial(self) -> bool:
        """Whether minor or patch was left out of the source text."""
        return self.minor is None or self.patch is None

    def complete(self, fill: int = 0) -> Version:
        """Return this version with the missing components filled in."""
        return replace(
            self,
            minor=self.minor if self.minor is not None else fill,
            patch=self.patch if self.patch is not None else fill,
        )

    def _key(self) -> tuple:
        """Comparison key following the precedence rules of semver 2.0.0."""
        prerelease = self.prerelease
        if prerelease:
            # A prerelease sorts before the release it leads to, and identifiers
            # are compared numerically when both are numeric, lexically otherwise.
            tail: tuple = (
                -1,
                tuple(
                    (0, int(part), "") if part.isdigit() else (1, 0, part) for part in prerelease
                ),
            )
        else:
            tail = (0, ())
        return (
            self.major,
            self.minor if self.minor is not None else 0,
            self.patch if self.patch is not None else 0,
            tail,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other: Version) -> bool:
        return self._key() < other._key()

    def __le__(self, other: Version) -> bool:
        return self._key() <= other._key()

    def __gt__(self, other: Version) -> bool:
        return self._key() > other._key()

    def __ge__(self, other: Version) -> bool:
        return self._key() >= other._key()

    def __hash__(self) -> int:
        return hash(self._key())


def parse(text: str) -> Version:
    """Parse a version, allowing a leading ``v`` and missing minor or patch."""
    if not isinstance(text, str):
        raise InvalidVersion(f"expected a string, got {type(text).__name__}")
    match = _VERSION_RE.match(text.strip())
    if not match:
        raise InvalidVersion(f"not a semantic version: {text!r}")
    prerelease = tuple(match.group("prerelease").split(".")) if match.group("prerelease") else ()
    for part in prerelease:
        if part.isdigit() and len(part) > 1 and part.startswith("0"):
            raise InvalidVersion(f"numeric prerelease identifier has a leading zero: {text!r}")
    minor = match.group("minor")
    patch = match.group("patch")
    return Version(
        major=int(match.group("major")),
        minor=int(minor) if minor is not None else None,
        patch=int(patch) if patch is not None else None,
        prerelease=prerelease,
        build=match.group("build") or "",
    )


Comparator = tuple[str, Version]
ComparatorSet = tuple[Comparator, ...]
Range = tuple[ComparatorSet, ...]

_COMPARATOR_RE = re.compile(r"^(<=|>=|<|>|=|\^|~)?\s*(.+)$")
_HYPHEN_RE = re.compile(r"^\s*(\S+)\s+-\s+(\S+)\s*$")


def _is_wildcard(text: str) -> bool:
    return text in ("*", "x", "X", "")


def _upper_bound(version: Version) -> Version:
    """The exclusive upper bound for a caret or tilde range."""
    if version.is_partial:
        # ^1 and ^1.2 widen to the next major; ^0.0 does not.
        if version.minor is None:
            return Version(version.major + 1, 0, 0)
        return Version(version.major, version.minor + 1, 0)
    if version.major:
        return Version(version.major + 1, 0, 0)
    if version.minor:
        return Version(0, version.minor + 1, 0)
    return Version(0, 0, version.patch + 1)


def _tilde_upper_bound(version: Version) -> Version:
    if version.minor is None:
        return Version(version.major + 1, 0, 0)
    return Version(version.major, version.minor + 1, 0)


def _wildcard_comparators(text: str) -> list[Comparator]:
    """Expand ``1.x``, ``1.2.X`` and ``*`` into a half-open comparator pair."""
    pieces = text.split(".")
    numbers: list[int] = []
    for piece in pieces:
        if _is_wildcard(piece):
            break
        if not piece.isdigit():
            raise InvalidRange(f"not a version in a range: {text!r}")
        numbers.append(int(piece))
    if not numbers:
        return []  # "*" puts no constraint on the set
    if len(numbers) == 1:
        return [(">=", Version(numbers[0], 0, 0)), ("<", Version(numbers[0] + 1, 0, 0))]
    if len(numbers) == 2:
        return [
            (">=", Version(numbers[0], numbers[1], 0)),
            ("<", Version(numbers[0], numbers[1] + 1, 0)),
        ]
    version = parse(text)
    return [("=", version)]


def _comparators_for(token: str) -> list[Comparator]:
    """Turn one whitespace separated token into comparators."""
    match = _COMPARATOR_RE.match(token)
    if not match:
        raise InvalidRange(f"cannot parse range token: {token!r}")
    operator, body = match.group(1) or "", match.group(2).strip()
    if operator in ("", "=") and any(_is_wildcard(p) for p in body.split(".")):
        return _wildcard_comparators(body)
    version = parse(body)
    if operator == "^":
        return [(">=", version.complete()), ("<", _upper_bound(version))]
    if operator == "~":
        return [(">=", version.complete()), ("<", _tilde_upper_bound(version))]
    if operator == "" and version.is_partial:
        # A bare partial version means the whole minor or major, as in npm.
        return _wildcard_comparators(str(version))
    if operator in ("", "="):
        if version.is_partial:
            return _wildcard_comparators(str(version))
        return [("=", version)]
    # A partial version after > or <= keeps the written precision, as in npm:
    # ">1.2" means ">=1.3.0" and "<=1.2" means "<1.3.0", while ">=1.2" and
    # "<1.2" only need the gaps filled with zero.
    if operator == ">" and version.is_partial:
        return [(">=", _upper_bound(version))]
    if operator == "<=" and version.is_partial:
        return [("<", _upper_bound(version))]
    if version.is_partial:
        return [(operator, version.complete())]
    return [(operator, version)]


def _hyphen_comparators(left: str, right: str) -> list[Comparator]:
    """Expand ``1.2.3 - 2.3`` into comparators."""
    low = parse(left)
    high = parse(right)
    comparators: list[Comparator] = [(">=", low.complete())]
    if high.is_partial:
        comparators.append(("<", _upper_bound(high)))
    else:
        comparators.append(("<=", high))
    return comparators


def parse_range(text: str) -> Range:
    """Parse a range into a tuple of comparator sets, one per ``||`` branch."""
    if not isinstance(text, str):
        raise InvalidRange(f"expected a string, got {type(text).__name__}")
    branches = [branch.strip() for branch in text.split("||")]
    if not branches or any(not branch for branch in branches):
        raise InvalidRange(f"empty range branch in {text!r}")
    sets: list[ComparatorSet] = []
    for branch in branches:
        hyphen = _HYPHEN_RE.match(branch)
        if hyphen:
            sets.append(tuple(_hyphen_comparators(hyphen.group(1), hyphen.group(2))))
            continue
        tokens = branch.replace(",", " ").split()
        comparators: list[Comparator] = []
        for token in tokens:
            try:
                comparators.extend(_comparators_for(token))
            except InvalidVersion as exc:
                raise InvalidRange(f"{exc} (in range {text!r})") from None
        sets.append(tuple(comparators))
    return tuple(sets)


def _set_matches(version: Version, comparator_set: ComparatorSet) -> bool:
    for operator, bound in comparator_set:
        if operator == "=" and version != bound:
            return False
        if operator == ">" and not version > bound:
            return False
        if operator == ">=" and not version >= bound:
            return False
        if operator == "<" and not version < bound:
            return False
        if operator == "<=" and not version <= bound:
            return False
    if version.prerelease:
        # A prerelease only matches a range that asks for a prerelease of the
        # same major.minor.patch, as in npm. "1.0.0-rc.1" satisfies neither
        # "^1.0.0" nor "*".
        for _, bound in comparator_set:
            if bound.prerelease and (
                bound.major,
                bound.minor or 0,
                bound.patch or 0,
            ) == (version.major, version.minor or 0, version.patch or 0):
                return True
        return False
    return True


def satisfies(version: str | Version, range_text: str) -> bool:
    """Whether ``version`` satisfies ``range_text``."""
    parsed = parse(version) if isinstance(version, str) else version
    return any(_set_matches(parsed, comparator_set) for comparator_set in parse_range(range_text))


def _iter_versions(versions: Iterable[str | Version]) -> Iterator[Version]:
    for version in versions:
        yield parse(version) if isinstance(version, str) else version


def sort_versions(versions: Iterable[str | Version]) -> list[Version]:
    """Return the versions in ascending precedence order."""
    return sorted(_iter_versions(versions))


def max_satisfying(versions: Iterable[str | Version], range_text: str) -> Version | None:
    """Return the highest version that satisfies ``range_text``, or ``None``."""
    matches = [v for v in _iter_versions(versions) if satisfies(v, range_text)]
    return max(matches) if matches else None


def min_satisfying(versions: Iterable[str | Version], range_text: str) -> Version | None:
    """Return the lowest version that satisfies ``range_text``, or ``None``."""
    matches = [v for v in _iter_versions(versions) if satisfies(v, range_text)]
    return min(matches) if matches else None


def filter_satisfying(versions: Sequence[str | Version], range_text: str) -> list[Version]:
    """Return every satisfying version, ascending."""
    return sort_versions(v for v in _iter_versions(versions) if satisfies(v, range_text))
