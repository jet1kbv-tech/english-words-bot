import os
import unittest
from unittest.mock import patch

from app.config import (
    DEFAULT_ADMIN_USERNAMES,
    DEFAULT_ALLOWED_USERNAMES,
    DEFAULT_DISPLAY_NAMES,
    DEFAULT_TEACHER_USERNAMES,
    _parse_display_names,
    _parse_usernames,
    load_settings,
)


class ParseUsernamesTests(unittest.TestCase):
    def test_splits_trims_and_normalizes(self) -> None:
        self.assertEqual(_parse_usernames(" Alice, @Bob , bob "), frozenset({"alice", "bob"}))

    def test_empty_value_yields_empty_set(self) -> None:
        self.assertEqual(_parse_usernames(""), frozenset())

    def test_blank_entries_are_dropped(self) -> None:
        self.assertEqual(_parse_usernames("alice,,  ,bob"), frozenset({"alice", "bob"}))


class ParseDisplayNamesTests(unittest.TestCase):
    def test_parses_username_colon_name_pairs(self) -> None:
        result = _parse_display_names("wp_bvv:Вова,privetnormalno:Саша")
        self.assertEqual(result, {"wp_bvv": "Вова", "privetnormalno": "Саша"})

    def test_normalizes_username_key(self) -> None:
        result = _parse_display_names("@Wp_Bvv : Вова")
        self.assertEqual(result, {"wp_bvv": "Вова"})

    def test_malformed_entry_without_colon_is_ignored(self) -> None:
        result = _parse_display_names("wp_bvv:Вова,justausername,privetnormalno:Саша")
        self.assertEqual(result, {"wp_bvv": "Вова", "privetnormalno": "Саша"})

    def test_empty_value_yields_empty_dict(self) -> None:
        self.assertEqual(_parse_display_names(""), {})


class LoadSettingsTests(unittest.TestCase):
    def _load(self, **env: str):
        base = {"BOT_TOKEN": "test-token"}
        base.update(env)
        with patch.dict(os.environ, base, clear=True), patch("app.config.load_dotenv"):
            return load_settings()

    def test_defaults_match_previously_hardcoded_values(self) -> None:
        settings = self._load()
        self.assertEqual(settings.allowed_usernames, frozenset({"privetnormalno"}))
        self.assertEqual(settings.admin_usernames, frozenset({"wp_bvv"}))
        self.assertEqual(settings.teacher_usernames, frozenset({"romateaches"}))
        self.assertEqual(settings.display_names, {"wp_bvv": "Вова", "privetnormalno": "Саша", "romateaches": "Roma"})

    def test_default_constants_are_consistent_with_each_other(self) -> None:
        # Guards against DEFAULT_* constants drifting out of sync with each other.
        self.assertEqual(_parse_usernames(DEFAULT_ALLOWED_USERNAMES), frozenset({"privetnormalno"}))
        self.assertEqual(_parse_usernames(DEFAULT_ADMIN_USERNAMES), frozenset({"wp_bvv"}))
        self.assertEqual(_parse_usernames(DEFAULT_TEACHER_USERNAMES), frozenset({"romateaches"}))
        self.assertEqual(
            _parse_display_names(DEFAULT_DISPLAY_NAMES),
            {"wp_bvv": "Вова", "privetnormalno": "Саша", "romateaches": "Roma"},
        )

    def test_env_vars_override_defaults(self) -> None:
        settings = self._load(
            ALLOWED_USERNAMES="privetnormalno, newstudent",
            ADMIN_USERNAMES="@Wp_Bvv",
            TEACHER_USERNAMES="romateaches",
            DISPLAY_NAMES="wp_bvv:Вова,privetnormalno:Саша,romateaches:Рома,newstudent:Новый ученик",
        )
        self.assertEqual(settings.allowed_usernames, frozenset({"privetnormalno", "newstudent"}))
        self.assertEqual(settings.admin_usernames, frozenset({"wp_bvv"}))
        self.assertEqual(settings.teacher_usernames, frozenset({"romateaches"}))
        self.assertEqual(settings.display_names["romateaches"], "Рома")
        self.assertEqual(settings.display_names["newstudent"], "Новый ученик")

    def test_missing_bot_token_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv"):
            with self.assertRaises(RuntimeError):
                load_settings()


if __name__ == "__main__":
    unittest.main()
