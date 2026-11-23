"""Tests for npm_semver."""

import pytest

from npm_semver import (
    InvalidRange,
    InvalidVersion,
    Version,
    filter_satisfying,
    max_satisfying,
    min_satisfying,
    parse,
    parse_range,
    satisfies,
    sort_versions,
)


class TestParse:
    def test_full_version(self):
        version = parse("1.2.3")
        assert (version.major, version.minor, version.patch) == (1, 2, 3)
        assert version.prerelease == ()
        assert version.build == ""
        assert not version.is_partial

    def test_leading_v_and_partials(self):
        assert parse("v1.2.3") == parse("1.2.3")
        assert parse("1.2").is_partial
        assert parse("1").is_partial
        assert str(parse("1.2")) == "1.2"

    def test_prerelease_and_build(self):
        version = parse("1.0.0-beta.11+build.7")
        assert version.prerelease == ("beta", "11")
        assert version.build == "build.7"
        assert str(version) == "1.0.0-beta.11+build.7"

    @pytest.mark.parametrize("text", ["", "one", "1.2.3.4", "1..3", "-1.0.0", "1.2.3-"])
    def test_rejects_nonsense(self, text):
        with pytest.raises(InvalidVersion):
            parse(text)

    def test_rejects_numeric_prerelease_with_leading_zero(self):
        with pytest.raises(InvalidVersion):
            parse("1.0.0-01")

    def test_rejects_non_string(self):
        with pytest.raises(InvalidVersion):
            parse(1.2)  # type: ignore[arg-type]


class TestPrecedence:
    def test_semver_order(self):
        ordered = [
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
            "1.0.1",
            "1.1.0",
        ]
        assert [str(v) for v in sort_versions(reversed(ordered))] == ordered

    def test_build_metadata_is_ignored(self):
        assert parse("1.0.0+build.1") == parse("1.0.0+build.9")

    def test_versions_hash_by_precedence(self):
        assert len({parse("1.0.0"), parse("v1.0.0"), parse("1.0.0+x")}) == 1


class TestRangeParsing:
    def test_or_branches(self):
        assert len(parse_range("1.x || >=2.0.0")) == 2

    def test_hyphen_range_becomes_two_comparators(self):
        comparators = parse_range("1.2.3 - 2.0.0")[0]
        assert [(op, str(v)) for op, v in comparators] == [
            (">=", "1.2.3"),
            ("<=", "2.0.0"),
        ]

    def test_commas_behave_like_spaces(self):
        assert parse_range(">=1.2.0, <2.0.0") == parse_range(">=1.2.0 <2.0.0")

    def test_wildcard_puts_no_constraint(self):
        assert parse_range("*") == ((),)

    @pytest.mark.parametrize("text", ["", "||", "1.2.3 ||", "not a range", "^"])
    def test_rejects_nonsense(self, text):
        with pytest.raises(InvalidRange):
            parse_range(text)


class TestSatisfies:
    @pytest.mark.parametrize(
        ("version", "range_text", "expected"),
        [
            ("1.4.2", "^1.2.0", True),
            ("2.0.0", "^1.2.0", False),
            ("1.2.0", "^1.2.0", True),
            ("0.2.4", "^0.2.3", True),
            ("0.3.0", "^0.2.3", False),
            ("0.0.3", "^0.0.3", True),
            ("0.0.4", "^0.0.3", False),
            ("1.9.9", "^1", True),
            ("2.0.0", "^1", False),
            ("0.5.0", "^0", True),
            ("1.0.0", "^0", False),
            ("1.2.9", "~1.2.3", True),
            ("1.3.0", "~1.2.3", False),
            ("1.2.9", "~1.2", True),
            ("1.3.0", "~1.2", False),
            ("1.9.0", "~1", True),
            ("2.0.0", "~1", False),
            ("1.2.3", "1.2.3", True),
            ("1.2.4", "1.2.3", False),
            ("1.2.5", "1.2", True),
            ("1.3.0", "1.2", False),
            ("1.9.0", "1.x", True),
            ("1.2.7", "1.2.x", True),
            ("1.3.0", "1.2.X", False),
            ("9.9.9", "*", True),
            ("1.4.0", ">1.2", True),
            ("1.2.9", ">1.2", False),
            ("1.2.9", ">=1.2", True),
            ("1.1.9", "<1.2", True),
            ("1.2.0", "<1.2", False),
            ("1.2.9", "<=1.2", True),
            ("1.3.0", "<=1.2", False),
            ("1.5.0", "1.2.3 - 2.0.0", True),
            ("2.0.0", "1.2.3 - 2.0.0", True),
            ("2.0.1", "1.2.3 - 2.0.0", False),
            ("1.2.0", "1.2 - 2.3", True),
            ("2.3.9", "1.2 - 2.3", True),
            ("2.4.0", "1.2 - 2.3", False),
            ("2.1.0", "1.x || >=2.0.0", True),
            ("3.0.0", "1.x || >=2.0.0", True),
            ("0.9.0", "1.x || >=2.0.0", False),
        ],
    )
    def test_ranges(self, version, range_text, expected):
        assert satisfies(version, range_text) is expected

    def test_accepts_a_parsed_version(self):
        assert satisfies(parse("1.4.2"), "^1.2.0")

    @pytest.mark.parametrize(
        ("version", "range_text", "expected"),
        [
            ("1.0.0-rc.1", "^1.0.0", False),
            ("1.0.0-rc.2", ">=1.0.0-rc.1", True),
            ("1.0.0-rc.1", ">=1.0.0-rc.1", True),
            ("1.2.0-rc.1", ">=1.0.0-rc.1", False),
            ("1.0.0-rc.1", "*", False),
            ("1.0.0", ">=1.0.0-rc.1", True),
        ],
    )
    def test_prereleases_need_a_prerelease_comparator(self, version, range_text, expected):
        assert satisfies(version, range_text) is expected


class TestSelection:
    versions = ["1.0.0", "1.4.2", "1.9.9", "2.0.0", "2.1.0-rc.1"]

    def test_max_satisfying(self):
        assert str(max_satisfying(self.versions, "^1.2.0")) == "1.9.9"

    def test_min_satisfying(self):
        assert str(min_satisfying(self.versions, "^1.2.0")) == "1.4.2"

    def test_no_match_returns_none(self):
        assert max_satisfying(self.versions, "^3.0.0") is None
        assert min_satisfying(self.versions, "^3.0.0") is None

    def test_filter_satisfying_is_sorted_and_complete(self):
        assert [str(v) for v in filter_satisfying(self.versions, ">=1.4.0")] == [
            "1.4.2",
            "1.9.9",
            "2.0.0",
        ]

    def test_max_satisfying_accepts_version_objects(self):
        assert max_satisfying([parse("1.0.0"), parse("2.0.0")], "<2.0.0") == Version(1, 0, 0)


class TestVersionHelpers:
    def test_str_round_trips_through_parse(self):
        for text in ["0.0.1", "1.2.3-alpha.1", "1.2.3+build"]:
            assert str(parse(text)) == text

    def test_complete_fills_missing_parts(self):
        assert str(parse("1.2").complete()) == "1.2.0"
        assert str(parse("1").complete()) == "1.0.0"

    def test_repr_is_readable(self):
        assert repr(parse("1.2.3")) == (
            "Version(major=1, minor=2, patch=3, prerelease=(), build='')"
        )

    def test_ordering_supports_chained_comparisons(self):
        assert parse("1.0.0") > parse("1.0.0-rc.1") < parse("1.0.0")
