#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""腾位策略测试。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import policy  # noqa: E402
from campusnet.models import Device  # noqa: E402


def dev(ip, add_time, os_name="Windows 10", ctype="1"):
    return Device(ip=ip, add_time=add_time, os_name=os_name, client_type=ctype)


def sample():
    return [
        dev("10.0.0.3", "2026-09-16 00:10:00"),   # 最新
        dev("10.0.0.1", "2026-09-12 21:50:49"),   # 最老
        dev("10.0.0.2", "2026-09-14 08:00:00"),   # 中间
    ]


class SortingTest(unittest.TestCase):
    def test_oldest_first(self):
        ordered = policy.sort_oldest_first(sample())
        self.assertEqual(["10.0.0.1", "10.0.0.2", "10.0.0.3"],
                         [d.ip for d in ordered])

    def test_newest_first(self):
        ordered = policy.sort_newest_first(sample())
        self.assertEqual(["10.0.0.3", "10.0.0.2", "10.0.0.1"],
                         [d.ip for d in ordered])

    def test_missing_time_sorts_last(self):
        devices = sample() + [dev("10.0.0.9", "")]
        ordered = policy.sort_oldest_first(devices)
        self.assertEqual("10.0.0.9", ordered[-1].ip)


class CandidatesTest(unittest.TestCase):
    def test_excludes_self(self):
        pool = policy.candidates(sample(), my_ip="10.0.0.2")
        self.assertNotIn("10.0.0.2", [d.ip for d in pool])
        self.assertEqual(2, len(pool))

    def test_without_my_ip_keeps_all(self):
        self.assertEqual(3, len(policy.candidates(sample())))


class PickVictimsTest(unittest.TestCase):
    def test_preselect_oldest_default(self):
        victims = policy.pick_victims(sample(), my_ip="10.0.0.3")
        self.assertEqual(["10.0.0.1"], [d.ip for d in victims])

    def test_skips_self_even_if_it_is_oldest(self):
        """预选到本机 IP 时顺延选下一台，避免"预选自己"这种无意义选择。"""
        victims = policy.pick_victims(sample(), my_ip="10.0.0.1")
        self.assertEqual(["10.0.0.2"], [d.ip for d in victims])

    def test_count_picks_multiple(self):
        victims = policy.pick_victims(sample(), my_ip="10.0.0.3", count=2)
        self.assertEqual(["10.0.0.1", "10.0.0.2"], [d.ip for d in victims])

    def test_manual_mode_selects_nothing(self):
        self.assertEqual([], policy.pick_victims(sample(), mode=policy.MANUAL))

    def test_priority_mode_kicks_least_important_first(self):
        prefs = [
            {"alias": "台式机", "priority": 1, "last_ip": "10.0.0.1"},  # 最重要
            {"alias": "备用机", "priority": 3, "last_ip": "10.0.0.3"},  # 最不重要
            {"alias": "笔记本", "priority": 2, "last_ip": "10.0.0.2"},
        ]
        victims = policy.pick_victims(sample(), mode=policy.PRIORITY,
                                      device_prefs=prefs)
        self.assertEqual(["10.0.0.3"], [d.ip for d in victims])

    def test_priority_mode_unknown_devices_go_last(self):
        prefs = [{"alias": "备用机", "priority": 3, "last_ip": "10.0.0.2"}]
        victims = policy.pick_victims(sample(), mode=policy.PRIORITY,
                                      device_prefs=prefs)
        self.assertEqual(["10.0.0.2"], [d.ip for d in victims])

    def test_empty_input(self):
        self.assertEqual([], policy.pick_victims([]))


class AliasTest(unittest.TestCase):
    def test_alias_lookup(self):
        prefs = [{"alias": "备用机", "priority": 3, "last_ip": "10.0.0.3"}]
        self.assertEqual("备用机", policy.alias_of(dev("10.0.0.3", ""), prefs))
        self.assertEqual("", policy.alias_of(dev("10.0.0.1", ""), prefs))

    def test_describe_victims_is_human_readable(self):
        import datetime as dt
        prefs = [{"alias": "备用机", "priority": 3, "last_ip": "10.0.0.3"}]
        now = dt.datetime(2026, 9, 16, 0, 10, 0)
        text = policy.describe_victims([dev("10.0.0.3", "2026-09-12 21:50:49")],
                                       prefs, now=now)
        self.assertIn("10.0.0.3", text)
        self.assertIn("备用机", text)
        self.assertIn("3 天", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
