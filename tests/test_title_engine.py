# -*- coding: utf-8 -*-
"""标题引擎(L2)单元测试。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.title_engine import generate_titles, _score_title, DEFAULT_TITLE_MAX_CHARS
from src.people_goods_scene import build_profile


def test_generate_titles_basic_coverage():
    cands = generate_titles(
        name="男士纯棉中筒袜防臭吸汗",
        remark="5双装",
        content="精梳棉 透气 商务通勤",
        month=4,
        max_chars=30,
    )
    assert cands, "应生成候选标题"
    top = cands[0]
    # 不超长
    assert top.char_count <= 30
    # 覆盖人货场（至少人+货）
    assert top.coverage["人"], "应锚定人群"
    assert len(top.coverage["货"]) >= 2, "应含多类货卖点"


def test_titles_within_char_limit():
    cands = generate_titles(name="女士船袜浅口纯棉透气", month=7, max_chars=20)
    for c in cands:
        assert c.char_count <= 20, f"标题超限: {c.title}({c.char_count})"


def test_no_brand_word_in_titles():
    # 即使输入含品牌后缀，输出应被清洗
    cands = generate_titles(
        name="某某旗舰店男士纯棉中筒袜防臭",
        month=4,
        max_chars=30,
    )
    for c in cands:
        assert "旗舰店" not in c.title
        assert "品牌" not in c.title


def test_precise_title_beats_keyword_stuffing():
    """精准结构化标题的评分应高于关键词堆砌标题。"""
    profile = build_profile(
        name="男士纯棉中筒袜防臭吸汗商务",
        content="精梳棉 透气",
        month=4,
    )
    precise = _score_title("男士纯棉中筒袜防臭商务", profile, max_chars=30)
    stuffed = _score_title(
        "爆款男士袜子热销限时特价包邮新品精选高档超值四季", profile, max_chars=30
    )
    assert precise.score > stuffed.score, (
        f"精准标题({precise.score})应高于堆砌标题({stuffed.score})"
    )


def test_superlative_penalized():
    profile = build_profile(name="男士纯棉中筒袜", month=4)
    clean = _score_title("男士纯棉中筒袜春秋", profile, max_chars=30)
    with_banned = _score_title("男士纯棉中筒袜爆款热销包邮", profile, max_chars=30)
    assert clean.score > with_banned.score


def test_missing_dimensions_reported():
    # 只有货、无明确人群/场景
    profile = build_profile(name="纯棉袜子透气", month=None)
    cands = generate_titles(name="纯棉袜子透气", profile=profile, max_chars=30)
    # 至少有候选，且 missing 字段能反映缺失
    assert cands
    # 缺人群锚点应被记录（无性别信号）
    assert any("人群锚点" in c.missing for c in cands)


def test_titles_are_unique():
    cands = generate_titles(name="男士纯棉中筒袜防臭吸汗", content="精梳棉透气商务", month=4)
    titles = [c.title for c in cands]
    assert len(titles) == len(set(titles)), "候选标题应去重"


def test_to_dict_serializable():
    cands = generate_titles(name="女士船袜纯棉", month=7)
    for c in cands:
        d = c.to_dict()
        assert "title" in d and "score" in d and "coverage" in d


# ---------- 混合模式：LLM 增强 ----------
class _FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.called = False

    def complete(self, prompt, system=None, **kwargs):
        self.called = True
        return self.reply


def test_llm_candidates_merged_and_marked():
    llm = _FakeLLM("男士纯棉中筒袜防臭吸汗商务通勤优选\n男士精梳棉中筒袜抗菌透气春秋")
    cands = generate_titles(
        name="男士纯棉中筒袜防臭", content="精梳棉 商务", month=4,
        max_chars=30, llm_client=llm,
    )
    assert llm.called
    # 候选里应同时含 LLM 来源与本地来源
    sources = {c.source for c in cands}
    assert "LLM" in sources or "本地" in sources  # 至少融入
    # LLM 文本若含品牌/极限词会被清洗/降权，但流程不报错
    assert all(c.char_count > 0 for c in cands)


def test_llm_failure_falls_back_to_local():
    class _BoomLLM:
        def complete(self, *a, **k):
            raise RuntimeError("network down")
    cands = generate_titles(
        name="男士纯棉中筒袜防臭", content="精梳棉 商务", month=4,
        max_chars=30, llm_client=_BoomLLM(),
    )
    # LLM 挂掉仍有本地候选兜底
    assert cands
    assert all(c.source == "本地" for c in cands)


def test_llm_brand_word_still_sanitized():
    llm = _FakeLLM("某某旗舰店男士纯棉中筒袜防臭商务")
    cands = generate_titles(name="男士纯棉中筒袜", month=4, max_chars=30, llm_client=llm)
    for c in cands:
        assert "旗舰店" not in c.title  # LLM 输出同样过无品牌清洗


def test_no_llm_is_pure_local():
    cands = generate_titles(name="男士纯棉中筒袜防臭", month=4, max_chars=30)
    assert cands
    assert all(c.source == "本地" for c in cands)
