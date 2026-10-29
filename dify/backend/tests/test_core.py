"""不依赖数据库的单元测试：python -m unittest discover -s tests"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.court import compute_sentence
from app.db import sanitize_fts
from app.embeddings import hash_embed
from app.statutes import STATUTES, infer_tag


class StatuteTests(unittest.TestCase):
    def test_codes_unique_and_complete(self) -> None:
        codes = [s.code for s in STATUTES]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertGreaterEqual(len(codes), 72)
        self.assertTrue(all(code.startswith("AB-") for code in codes))

    def test_ranges_valid(self) -> None:
        for statute in STATUTES:
            self.assertLessEqual(statute.min_days, statute.max_days, statute.code)
            self.assertGreaterEqual(statute.severity, 1)
            self.assertTrue(statute.text and statute.keywords and statute.fine)

    def test_tag_inference(self) -> None:
        self.assertEqual(infer_tag("我的猫凌晨三点在我脸上蹦迪"), "宠物")
        self.assertEqual(infer_tag("我要告周一，它每周都带来早高峰"), "时间")
        self.assertEqual(infer_tag("室友的袜子在我枕头底下"), "室友")
        self.assertIsNone(infer_tag("你好呀，随便聊聊"))


class SentenceTests(unittest.TestCase):
    def test_within_bounds(self) -> None:
        for absurdity in (0, 50, 100):
            for attitude in ("认罪", "狡辩", "卖惨", "沉默"):
                value, upper = compute_sentence(
                    min_days=3, max_days=15, absurdity=absurdity, attitude=attitude, prior_convictions=0
                )
                self.assertGreaterEqual(value, 3)
                self.assertLessEqual(value, 15)
                self.assertEqual(upper, 15)

    def test_recidivism_raises_upper_bound(self) -> None:
        _, upper1 = compute_sentence(min_days=1, max_days=7, absurdity=80, attitude="狡辩", prior_convictions=1)
        _, upper3 = compute_sentence(min_days=1, max_days=7, absurdity=80, attitude="狡辩", prior_convictions=3)
        self.assertEqual(upper1, 10)
        self.assertEqual(upper3, 16)

    def test_attitude_affects_result(self) -> None:
        admit, _ = compute_sentence(min_days=1, max_days=30, absurdity=90, attitude="认罪", prior_convictions=0)
        quibble, _ = compute_sentence(min_days=1, max_days=30, absurdity=90, attitude="狡辩", prior_convictions=0)
        self.assertGreater(quibble, admit)


class EmbeddingTests(unittest.TestCase):
    def test_deterministic_and_normalized(self) -> None:
        first = hash_embed("猫 凌晨 蹦迪 水杯", 128)
        second = hash_embed("猫 凌晨 蹦迪 水杯", 128)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 128)
        norm = math.sqrt(sum(v * v for v in first))
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_similar_text_scores_higher(self) -> None:
        base = hash_embed("猫在凌晨蹦迪打翻水杯", 128)
        close = hash_embed("猫 凌晨 蹦迪 水杯", 128)
        far = hash_embed("周一 早高峰 会议", 128)
        dot_close = sum(a * b for a, b in zip(base, close))
        dot_far = sum(a * b for a, b in zip(base, far))
        self.assertGreater(dot_close, dot_far)


class TextTests(unittest.TestCase):
    def test_sanitize_fts(self) -> None:
        self.assertEqual(sanitize_fts("猫，凌晨！蹦迪？？"), "猫 凌晨 蹦迪")
        self.assertNotIn("'", sanitize_fts("'; DROP TABLE statutes; --"))
        self.assertTrue(sanitize_fts(""))


if __name__ == "__main__":
    unittest.main()
