#!/usr/bin/env python3
"""
Tests for person-type property conversion.

Notion renders a person/created_by/last_edited_by cell as
    <span class="user">
      <span class="icon ... user-icon"><span class="user-icon-inner">D</span></span>
      Dana Rivera
    </span>
The avatar carries the initial letter as text, so a naive get_text() glues it
onto the name ("DDana Rivera"). convert_property_value must strip the avatar
icon before reading the name.

(Names below are fictional fixtures — no real data in this public repo.)

Run:  /usr/bin/python3 "Notion Database to Obsidian/test_person_property.py"
"""

import importlib.util
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

_MOD_PATH = Path(__file__).with_name("notion_db_to_obsidian.py")
_spec = importlib.util.spec_from_file_location("notion_db_to_obsidian", _MOD_PATH)
ndo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndo)


def td(inner: str):
    return BeautifulSoup(f"<td>{inner}</td>", "html.parser").find("td")


def user(initial: str, name: str) -> str:
    return (
        '<span class="user">'
        f'<span class="icon text-icon user-icon"><span class="user-icon-inner">{initial}</span></span>'
        f"{name}"
        "</span>"
    )


USER_1 = user("D", "Dana Rivera")
USER_2 = user("A", "Alex Kim")


class PersonAvatarInitial(unittest.TestCase):
    def test_person_strips_avatar_initial(self):
        self.assertEqual(ndo.convert_property_value("person", td(USER_1)), "Dana Rivera")

    def test_created_by_strips_avatar_initial(self):
        self.assertEqual(ndo.convert_property_value("created_by", td(USER_1)), "Dana Rivera")

    def test_last_edited_by_strips_avatar_initial(self):
        self.assertEqual(ndo.convert_property_value("last_edited_by", td(USER_1)), "Dana Rivera")

    def test_multiple_users_each_stripped(self):
        self.assertEqual(
            ndo.convert_property_value("person", td(USER_1 + USER_2)),
            ["Dana Rivera", "Alex Kim"],
        )

    def test_user_without_avatar_unaffected(self):
        self.assertEqual(
            ndo.convert_property_value("person", td('<span class="user">Sam Lee</span>')),
            "Sam Lee",
        )

    def test_empty_person_cell_is_none(self):
        self.assertIsNone(ndo.convert_property_value("person", td("")))

    def test_user_with_icon_but_no_name_is_none_not_doubled(self):
        # Icon present, no readable name -> None, not the doubled avatar initial.
        html = (
            '<span class="user">'
            '<span class="icon text-icon user-icon"><span class="user-icon-inner">J</span></span>'
            "</span>"
        )
        self.assertIsNone(ndo.convert_property_value("person", td(html)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
