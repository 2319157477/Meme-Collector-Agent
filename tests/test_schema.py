from __future__ import annotations

import unittest

from meme_collector_app.schemas import MemeCandidate, render_meme_markdown
from meme_collector_app.services.agent import parse_candidates
from meme_collector_app.services.dedupe import is_duplicate_name, normalize_name


class SchemaRenderingTests(unittest.TestCase):
    def sample_candidate(self) -> MemeCandidate:
        return MemeCandidate(
            name="电子榨菜",
            meme_type="流行语",
            heat_level="🔥🔥",
            popularity_period="2026上半年",
            derivative_potential="高",
            platforms=["B站", "抖音"],
            meaning="指吃饭时搭配观看的轻松内容，像榨菜一样下饭。常用于调侃短视频或综艺内容很适合放松观看。",
            catchphrases=["今晚吃点电子榨菜"],
            origin="网络用语演化",
            emotion_tags=["搞笑", "放松"],
            scenarios=["日常", "美食"],
            usage_examples=["下班吃饭时打开综艺：今晚配点电子榨菜。"],
            script_integration_guide="适合让疲惫角色在吃饭时说，用来制造生活化喜剧效果。",
            source_urls=["https://example.com/meme"],
            confidence=0.8,
        )

    def test_render_contains_required_sections(self) -> None:
        markdown = render_meme_markdown(self.sample_candidate())
        for section in [
            "# 电子榨菜",
            "## 基本信息",
            "## 含义解释",
            "## 金句台词",
            "## 出处来源",
            "## 情感标签",
            "## 适用场景",
            "## 使用场景示例",
            "## 剧本融入指南",
        ]:
            self.assertIn(section, markdown)

    def test_name_normalization_detects_practical_duplicates(self) -> None:
        self.assertEqual(normalize_name("《电子-榨菜》!"), normalize_name("电子榨菜"))
        self.assertTrue(is_duplicate_name("电子榨菜", {"《电子-榨菜》!"}))

    def test_parse_agent_candidates(self) -> None:
        raw = '{"candidates": [' + self.sample_candidate().model_dump_json() + ']}'
        parsed = parse_candidates(raw)
        self.assertEqual(parsed[0].name, "电子榨菜")


if __name__ == "__main__":
    unittest.main()
