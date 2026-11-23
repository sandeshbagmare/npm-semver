# Changelog

## 0.1.1

- Badges in the README, shared by the GitHub and PyPI pages.

## 0.1.0

First release.

- `parse`, `Version` with semver 2.0.0 precedence.
- `parse_range`, `satisfies`, `max_satisfying`, `min_satisfying`, `filter_satisfying`,
  `sort_versions`.
- Range syntax: exact, caret, tilde, comparison, wildcard, partial, hyphen, `||`.
- npm's prerelease rule: a prerelease matches only a range that names a prerelease of
  the same `major.minor.patch`.
