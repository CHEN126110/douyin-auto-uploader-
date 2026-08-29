# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.professional_title_generator import (  # noqa: E402
    ProfessionalTitleGenerator,
    audit_no_brand_title_text,
    sanitize_no_brand_title_text,
)
from src.trending_keywords_scraper import TrendingKeywordsScraper  # noqa: E402


class ProfessionalTitleNoBrandPolicyTest(unittest.TestCase):
    def test_title_templates_do_not_accept_brand_slot(self) -> None:
        generator = ProfessionalTitleGenerator()

        self.assertTrue(generator.title_templates)
        for template in generator.title_templates:
            self.assertNotIn("{brand}", template)

    def test_title_sanitizer_removes_no_brand_and_source_brand_markers(self) -> None:
        title = sanitize_no_brand_title_text("songmu淞木 布标薄款中筒袜女 无品牌 官方旗舰店")

        self.assertEqual(title, "布标薄款中筒袜女")

    def test_title_sanitizer_removes_leftover_quotes_after_source_brand(self) -> None:
        title = sanitize_no_brand_title_text('songmu淞木" 布标镂空无骨袜子女')

        self.assertEqual(title, "布标镂空无骨袜子女")

    def test_long_tail_keywords_avoid_brand_comparison_terms(self) -> None:
        scraper = object.__new__(TrendingKeywordsScraper)
        scraper.high_value_modifiers = {"功能性": ["防臭", "透气"]}

        keywords = scraper._generate_long_tail_keywords("短袜")

        keyword_text = " ".join(item.keyword for item in keywords)
        self.assertNotIn("品牌", keyword_text)
        self.assertNotIn("牌子", keyword_text)

    def test_no_brand_title_audit_flags_source_brand_prefix_without_style_false_positive(self) -> None:
        risky = audit_no_brand_title_text("KIKISOCKS袜子女春夏薄款透气花边微压中筒韩系甜美少女风")
        safe = audit_no_brand_title_text("无骨堆堆袜子纯棉女学院风夏季薄款白色女袜中筒袜灰色jk透气长袜")

        self.assertTrue(risky["has_risk"])
        self.assertIn("source_brand_like_prefix", risky["risk_flags"])
        self.assertEqual(risky["sanitized_title"], "袜子女春夏薄款透气花边微压中筒韩系甜美少女风")
        self.assertFalse(safe["has_risk"])


if __name__ == "__main__":
    unittest.main()
