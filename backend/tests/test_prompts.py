"""分层/角色化提示词的单元测试：渲染、角色归属、空层跳过、花括号安全。

不触网：仅验证模板组装逻辑（Role → system，task_layers → user）。
"""
from __future__ import annotations

import pytest

import prompts
from prompts import roles, summary, transcript, translate

# 每个 Prompt 一组可渲染的代表性变量
_RENDER_CASES = [
    (transcript.DOMAIN_INFER, {"title_hint": "", "sample": "采样文本"}),
    (transcript.OPTIMIZE_ZH, {"domain_block": "", "chunk_text": "原文"}),
    (transcript.OPTIMIZE_EN, {"domain_block": "", "chunk_text": "raw"}),
    (summary.SINGLE, {"language_name": "中文（简体）", "transcript": "T"}),
    (summary.CHUNK, {"language_name": "EN", "part": 1, "total": 3, "chunk": "C"}),
    (summary.INTEGRATE, {"language_name": "EN", "combined_summaries": "S"}),
    (summary.TWO_STEP_1, {"language_name": "EN", "preview": "P"}),
    (
        summary.TWO_STEP_2,
        {"custom_prompt": "be terse", "language_name": "EN", "transcript_for_summary": "T"},
    ),
    (
        translate.SINGLE,
        {"source_lang_name": "English", "target_lang_name": "中文", "text": "hi"},
    ),
    (
        translate.CHUNK,
        {"source_lang_name": "English", "target_lang_name": "中文", "text": "hi",
         "part": 2, "total": 5},
    ),
]


class TestRendering:
    @pytest.mark.parametrize("prompt, variables", _RENDER_CASES)
    def test_renders_to_system_and_user(self, prompt, variables):
        messages = prompt.render(**variables)
        assert [m["role"] for m in messages] == ["system", "user"]
        # 角色（system）与任务（user）均非空（双步 Step2 的 system 也来自 custom_prompt）
        assert messages[0]["content"].strip()
        assert messages[1]["content"].strip()

    @pytest.mark.parametrize("prompt, variables", _RENDER_CASES)
    def test_no_unfilled_placeholders(self, prompt, variables):
        for m in prompt.render(**variables):
            assert "{" not in m["content"] and "}" not in m["content"]


class TestRoleAssignment:
    def test_system_opens_with_role_identity(self):
        messages = summary.SINGLE.render(language_name="EN", transcript="T")
        # 身份层置于 system 最前——「赋予角色」是第一道约束
        assert messages[0]["content"].startswith("You are an expert editor.")

    def test_transcript_rules_live_in_system_not_user(self):
        # 角色化后，内容/分段/输出规则属于角色恒定行为，归 system；user 只承载输入
        messages = transcript.OPTIMIZE_ZH.render(domain_block="", chunk_text="原文XYZ")
        system, user = messages[0]["content"], messages[1]["content"]
        assert "**内容优化（正确性优先）：**" in system
        assert "<transcript>" in system
        assert "原文XYZ" in user
        assert "**内容优化" not in user

    def test_chunk_translator_has_part_context_in_system(self):
        messages = translate.CHUNK.render(
            source_lang_name="English", target_lang_name="中文", text="hi", part=2, total=5
        )
        assert "第2部分" in messages[0]["content"]
        assert "共5部分" in messages[0]["content"]


class TestOptionalLayerSkipping:
    def test_empty_domain_block_skipped(self):
        messages = transcript.OPTIMIZE_ZH.render(domain_block="", chunk_text="原文")
        user = messages[1]["content"]
        # 空 domain 层不应留下「领域与纠偏约束」标题或多余空行
        assert "领域与纠偏约束" not in user
        assert "\n\n\n" not in user

    def test_present_domain_block_included(self):
        block = "**领域与纠偏约束（预分析，仅供参考）：**\n【内容类型】访谈"
        messages = transcript.OPTIMIZE_ZH.render(domain_block=block, chunk_text="原文")
        assert "【内容类型】访谈" in messages[1]["content"]


class TestBraceSafety:
    def test_custom_prompt_with_literal_braces(self):
        # Step1 产出的 custom_prompt 可能含 {…}，作为「值」注入不得触发二次解析
        messages = summary.TWO_STEP_2.render(
            custom_prompt="output strictly as {json}",
            language_name="EN",
            transcript_for_summary="T",
        )
        assert "output strictly as {json}" in messages[0]["content"]


class TestRoleStructure:
    def test_role_as_layers_order(self):
        role = roles.SUMMARY_EDITOR
        names = [l.name for l in role.as_layers()]
        assert names[0].endswith("/identity")
        assert names[-1] == "output_contract"

    def test_role_without_directives(self):
        # SUMMARY_EXECUTOR 仅 identity + output_contract（人设是动态注入的）
        names = [l.name for l in roles.SUMMARY_EXECUTOR.as_layers()]
        assert names == ["summary_executor/identity", "hard_rules"]
