from dataclasses import dataclass
import unittest

from app.auth.roles import Role, RoleResolver, get_user_role, is_user_allowed


@dataclass(frozen=True)
class RoleSettings:
    allowed_usernames: frozenset[str] = frozenset({"privetnormalno"})
    admin_usernames: frozenset[str] = frozenset({"wp_bvv"})
    teacher_usernames: frozenset[str] = frozenset({"romateaches"})


class RoleResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = RoleSettings()

    def test_wp_bvv_is_admin(self) -> None:
        self.assertEqual(get_user_role("wp_bvv", self.settings), Role.ADMIN)

    def test_romateaches_is_teacher(self) -> None:
        self.assertEqual(get_user_role("romateaches", self.settings), Role.TEACHER)

    def test_privetnormalno_is_student(self) -> None:
        self.assertEqual(get_user_role("privetnormalno", self.settings), Role.STUDENT)

    def test_role_resolution_is_case_insensitive(self) -> None:
        self.assertEqual(get_user_role("@WP_BVV", self.settings), Role.ADMIN)
        self.assertTrue(is_user_allowed("ROMATEACHES", self.settings))
        self.assertTrue(is_user_allowed("PrivetNormalno", self.settings))

    def test_none_username_does_not_crash(self) -> None:
        self.assertEqual(get_user_role(None, self.settings), Role.STUDENT)
        self.assertFalse(is_user_allowed(None, self.settings))

    def test_resolver_exposes_only_student_allowed_usernames(self) -> None:
        resolver = RoleResolver(self.settings)
        self.assertEqual(resolver.student_usernames, {"privetnormalno"})


if __name__ == "__main__":
    unittest.main()
