"""LLM access layer with a deterministic offline mock.

Two providers are supported:

* ``deepseek`` -- OpenAI-compatible endpoint at ``https://api.deepseek.com``.
* ``mock``     -- no network, returns content derived from the constraints so
                  that the whole pipeline (generate -> render -> validate) can be
                  exercised without an API key or a budget.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .constraints import UnitConstraints

SYSTEM_PROMPT = """你是一位高职院校计算机专业教师，正在制作课件。
你必须严格遵守用户给出的知识图谱约束：概念覆盖、讲解顺序、纠错要求、禁用概念。
输出必须是合法 JSON，不要包裹在 Markdown 代码块中，不要输出任何解释性文字。"""

USER_TEMPLATE = """请根据以下约束生成课件。

{constraints}

## 输出格式
{{
  "unit_id": "{unit_id}",
  "slides": [
    {{
      "index": 1,
      "layout": "title|objectives|concept|comparison|code|misconception|summary",
      "title": "页面标题，不超过 20 字",
      "bullets": ["要点1", "要点2", "要点3"],
      "code": "可选的 Python 代码片段，没有则留空字符串",
      "notes": "讲稿备注，2-3 句",
      "concept_ids": ["该页讲解的概念 ID"],
      "background": false
    }}
  ]
}}

## 硬性要求
1. 共生成 {slide_budget} 页，第 1 页为标题页，最后一页为小结页。
2. 必须覆盖列表中的全部「必须覆盖的概念」，每个概念至少在一页的 concept_ids 中出现。
3. 页面顺序必须遵循给定的讲解顺序，不得倒置先修关系。
4. 每页 bullets 不超过 4 条，单条不超过 40 字，避免整段文字。
5. 若存在「必须纠正的典型误区」，必须有至少一页 layout 为 misconception 的页面专门处理。
6. 不要引入「禁止引入的概念」；确需提及时把 background 设为 true。
"""


@dataclass
class LLMConfig:
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.3
    max_tokens: int = 8000


class LLMError(RuntimeError):
    """Raised when the model returns something unusable."""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.S)
    return fence.group(1) if fence else text


class LLMClient:
    """Thin wrapper over an OpenAI-compatible chat completion endpoint."""

    def __init__(self, config: LLMConfig | None = None, force_mock: bool = False) -> None:
        self.config = config or LLMConfig()
        self.mock = force_mock or self.config.provider == "mock"
        self._client = None
        if not self.mock:
            api_key = os.environ.get(self.config.api_key_env, "")
            if not api_key:
                raise LLMError(
                    f"环境变量 {self.config.api_key_env} 未设置。"
                    "可设置后重试，或使用 --mock 运行离线演示。"
                )
            from openai import OpenAI  # imported lazily to keep mock mode light

            self._client = OpenAI(api_key=api_key, base_url=self.config.base_url)

    # ------------------------------------------------------------- public
    def generate_slides(self, constraints: UnitConstraints) -> dict[str, Any]:
        if self.mock:
            return self._mock_payload(constraints)

        prompt = USER_TEMPLATE.format(
            constraints=constraints.to_prompt_block(),
            unit_id=constraints.unit_id,
            slide_budget=constraints.slide_budget,
        )
        raw = self._chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        return self._parse(raw)

    # ------------------------------------------------------------ private
    def _chat(self, messages: list[dict[str, str]]) -> str:
        assert self._client is not None
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise LLMError("模型返回空内容")
        return content

    def _parse(self, raw: str) -> dict[str, Any]:
        try:
            payload = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError as exc:
            raise LLMError(f"模型未返回合法 JSON: {exc}\n原始输出前 500 字符:\n{raw[:500]}") from exc
        if "slides" not in payload or not isinstance(payload["slides"], list):
            raise LLMError("返回 JSON 缺少 slides 数组")
        return payload

    # --------------------------------------------------------------- mock
    def _mock_payload(self, c: UnitConstraints) -> dict[str, Any]:
        """Deterministic offline output used for tests and demos.

        It deliberately mirrors the contract closely, but mentions one forbidden
        concept so that the validator has something to catch.
        """
        slides: list[dict[str, Any]] = []

        slides.append(
            {
                "index": 1,
                "layout": "title",
                "title": c.unit_name,
                "bullets": [c.objective],
                "code": "",
                "notes": f"本讲次共 {c.slide_budget} 页，围绕 {len(c.required)} 个核心概念展开。",
                "concept_ids": [],
                "background": False,
            }
        )
        slides.append(
            {
                "index": 2,
                "layout": "objectives",
                "title": "学习目标",
                "bullets": [f"掌握 {n['name']}" for n in c.required[:4]],
                "code": "",
                "notes": "先明确本讲要解决的问题，再逐层展开。",
                "concept_ids": [],
                "background": False,
            }
        )

        concept_slides = max(c.slide_budget - 3, 1)
        buckets = self._chunk(c.required, concept_slides)
        for bucket in buckets:
            head = bucket[0]
            bullets = [f"{n['name']}：{n['definition']}" for n in bucket][:4]
            code = head.get("pseudocode", "") or ""
            slides.append(
                {
                    "index": len(slides) + 1,
                    "layout": "code" if code else "concept",
                    "title": "、".join(n["name"] for n in bucket)[:20],
                    "bullets": bullets,
                    "code": code,
                    "notes": f"讲解 {'、'.join(n['name'] for n in bucket)}，配合板书推导。",
                    "concept_ids": [n["id"] for n in bucket],
                    "background": False,
                }
            )

        for mc in c.misconceptions[:2]:
            slides.append(
                {
                    "index": len(slides) + 1,
                    "layout": "misconception",
                    "title": f"常见错误：{mc['statement'][:12]}",
                    "bullets": [f"错误说法：{mc['statement']}", f"正确理解：{mc['correction']}"],
                    "code": "",
                    "notes": "先让学生判断对错，再给反例演示。",
                    "concept_ids": [mc["id"]],
                    "background": False,
                }
            )

        slides.append(
            {
                "index": len(slides) + 1,
                "layout": "summary",
                "title": "小结",
                "bullets": [f"{n['name']}" for n in c.required[:4]],
                "code": "",
                "notes": "回顾本讲要点，布置上机任务。",
                "concept_ids": [],
                "background": False,
            }
        )

        return {"unit_id": c.unit_id, "slides": slides}

    @staticmethod
    def _chunk(items: list[dict[str, Any]], parts: int) -> list[list[dict[str, Any]]]:
        if not items:
            return []
        parts = max(1, min(parts, len(items)))
        size, remainder = divmod(len(items), parts)
        out: list[list[dict[str, Any]]] = []
        cursor = 0
        for i in range(parts):
            take = size + (1 if i < remainder else 0)
            out.append(items[cursor : cursor + take])
            cursor += take
        return out
