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
import time
from dataclasses import dataclass
from typing import Any

from .constraints import UnitConstraints

SYSTEM_PROMPT = """你是一位高职院校计算机专业教师，正在制作课件。
输出必须是合法 JSON，不要包裹在 Markdown 代码块中，不要输出任何解释性文字。"""

JSON_SPEC = """## 输出格式（Output a single valid JSON object）
{
  "unit_id": "...",
  "slides": [
    {
      "index": 1,
      "layout": "title|objectives|concept|comparison|code|misconception|summary",
      "title": "页面标题，不超过 20 字",
      "bullets": ["要点1", "要点2", "要点3"],
      "code": "可选的 Python 代码片段，没有则留空字符串",
      "notes": "讲稿备注，2-3 句",
      "concept_ids": ["该页讲解的概念 ID"],
      "background": false
    }
  ]
}

只返回 JSON 对象本身，不要 Markdown 代码块、不要前后解释。"""

RULES_CONSTRAINED = """## 硬性要求
1. 共生成 {slide_budget} 页，第 1 页为标题页，最后一页为小结页。
2. 必须覆盖列表中的全部「必须覆盖的概念」，每个概念至少在一页的 concept_ids 中出现。
3. 页面顺序必须遵循给定的讲解顺序，不得倒置先修关系。
4. 每页 bullets 不超过 4 条，单条不超过 40 字，避免整段文字。
5. 若存在「必须纠正的典型误区」，必须有至少一页 layout 为 misconception 的页面专门处理。
6. 不要引入「禁止引入的概念」；确需提及时把 background 设为 true。"""

RULES_BASELINE = """## 要求
1. 共生成 {slide_budget} 页，第 1 页为标题页，最后一页为小结页。
2. 每页 bullets 不超过 4 条，单条不超过 40 字，避免整段文字。
3. 讲哪些知识点、按什么顺序讲，由你自行判断。"""

# Padding for the length-matched placebo condition.  It must be about课件写作,
# not about this course: the point is to spend the same number of prompt tokens
# without handing over any course-specific structure.
PLACEBO_GUIDANCE = """## 课件写作的一般建议
1. 每页只承载一个中心论点，标题写成陈述句而不是名词短语。
2. 概念先用一句话下定义，再给一个具体例子，最后给一个反例。
3. 代码页保留可运行的最小片段，变量名要有意义，避免单字母命名。
4. 对比类内容用表格的思维组织：同一维度逐行比较，不要逐段叙述。
5. 知识点的展开应遵循「先具体、后抽象、再回到具体」的节奏。
6. 每 3 到 4 页安排一次小结或提问，帮助学生自查理解程度。
7. 避免在正文里堆砌整段文字，讲稿内容放到备注里。
8. 术语首次出现时给出中英文对照，后续统一使用中文。
9. 涉及计算的地方写清中间步骤，不要直接给结果。
10. 结尾留一个开放性问题，把本讲内容与后续讲次连起来。"""


def _pad_to(prompt: str, target_chars: int, filler: str) -> str:
    """Append whole blocks of ``filler`` until ``prompt`` reaches a length.

    Used only by the placebo condition, so that "the constrained prompt is
    longer" cannot be offered as an explanation for its results.
    """
    block = "\n\n" + filler
    while len(prompt) < target_chars:
        prompt += block
    return prompt

# Experimental conditions.
#
# ``full`` is the proposed method.  ``zero_shot`` / ``rag`` / ``cot`` are
# baselines that receive progressively less structural information.  The
# ``no_*`` conditions are *ablations*: they keep the full prompt but delete one
# graph-derived block, so each metric can be attributed to a specific part of
# the graph rather than to "the prompt" in general.
BASELINE_MODES = ("full", "rag_mc", "rag", "placebo", "cot", "zero_shot")
ABLATION_MODES = ("no_order", "no_misconception", "no_forbidden")
MODES = BASELINE_MODES + ABLATION_MODES


def _build_prompt(c: UnitConstraints, mode: str) -> str:
    """Compose the user prompt for one experimental condition."""
    course = c.course_name or "Python 数据结构"
    head = f"请为高职《{course}》课程第 {c.unit_order} 讲「{c.unit_name}」制作一份课件。"

    if mode == "full":
        return (
            f"请根据以下约束生成课件。\n\n{c.to_prompt_block()}\n\n"
            f"{JSON_SPEC}\n\n{RULES_CONSTRAINED.format(slide_budget=c.slide_budget)}"
        )

    ablations = {
        "no_order": {"include_order": False},
        "no_misconception": {"include_misconceptions": False},
        "no_forbidden": {"include_forbidden": False},
    }
    if mode in ablations:
        block = c.to_prompt_block(**ablations[mode])
        # Keep the rule text identical to `full`; only the data block shrinks.
        # Otherwise the ablation would also remove the instruction that asks
        # the model to honour the order, and the comparison would be unfair.
        rules = _drop_rule(RULES_CONSTRAINED, mode)
        return (
            f"请根据以下约束生成课件。\n\n{block}\n\n"
            f"{JSON_SPEC}\n\n{rules.format(slide_budget=c.slide_budget)}"
        )

    if mode == "zero_shot":
        return f"{head}\n\n{JSON_SPEC}\n\n{RULES_BASELINE.format(slide_budget=c.slide_budget)}"
    if mode == "rag":
        fragments = "\n".join(
            f"- {n['name']}：{n['definition']}" for n in c.required + c.optional
        )
        return (
            f"{head}\n\n## 教材片段\n{fragments}\n\n{JSON_SPEC}\n\n"
            f"{RULES_BASELINE.format(slide_budget=c.slide_budget)}"
        )
    if mode == "rag_mc":
        # Control for the obvious objection to the misconception result: "you
        # only score higher because the answer was written into the prompt".
        # Here the same misconception text is handed over as a flat retrieval
        # fragment -- no order, no forbidden list, no coverage list, no
        # dedicated layout instruction.  If `full` still wins on
        # misconception_coverage, the gain comes from structure, not from the
        # mere presence of the text.
        fragments = "\n".join(
            f"- {n['name']}：{n['definition']}" for n in c.required + c.optional
        )
        extra = "\n".join(
            f"- {mc['statement']}（正确理解：{mc['correction']}）"
            for mc in c.misconceptions
        )
        return (
            f"{head}\n\n## 教材片段\n{fragments}\n\n## 学生常见错误\n{extra}\n\n"
            f"{JSON_SPEC}\n\n{RULES_BASELINE.format(slide_budget=c.slide_budget)}"
        )
    if mode == "cot":
        return (
            f"{head}\n\n{JSON_SPEC}\n\n"
            f"{RULES_BASELINE.format(slide_budget=c.slide_budget)}\n"
            "4. 先在每页 notes 中说明该页在整讲中的定位与前后衔接，再写页面内容。"
        )
    if mode == "placebo":
        # Same token budget as `full`, zero course-specific structure.  If the
        # constrained condition still wins here, the gain is knowledge, not
        # prompt length.
        base = f"{head}\n\n{JSON_SPEC}\n\n{RULES_BASELINE.format(slide_budget=c.slide_budget)}"
        target = len(_build_prompt(c, "full"))
        return _pad_to(base, target, PLACEBO_GUIDANCE)
    raise ValueError(f"unknown mode: {mode}（可选 {', '.join(MODES)}）")


def _drop_rule(rules: str, mode: str) -> str:
    """Remove the rule line that would leak the ablated information back in."""
    drop_prefix = {
        "no_order": "3.",
        "no_misconception": "5.",
        "no_forbidden": "6.",
    }[mode]
    kept = [
        line
        for line in rules.splitlines()
        if not line.startswith(drop_prefix)
    ]
    return "\n".join(kept)


@dataclass
class LLMConfig:
    provider: str = "deepseek"
    # Official DeepSeek API model ids (as of 2026-11).
    # deepseek-chat / deepseek-reasoner were deprecated on 2026-07-24 and now
    # only survive as compatibility aliases for v4-flash thinking modes.
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.3
    max_tokens: int = 16000
    max_retries: int = 2
    # "default" keeps the model's built-in thinking pass; "disabled" turns it
    # off.  Measurements on 2026-11 show deepseek-v4-flash emits reasoning
    # tokens by default, which would silently confound a chain-of-thought
    # baseline -- so the setting is recorded per run instead of assumed.
    thinking: str = "default"


class LLMError(RuntimeError):
    """Raised when the model returns something unusable."""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.S)
    return fence.group(1) if fence else text


def _repair_json(text: str) -> str:
    """Conservative repairs for the malformations JSON mode still emits.

    Only two transformations, both semantics-preserving:

    1. drop the commas JSON forbids (before ``]`` or ``}`);
    2. close a response truncated mid-array, by appending the missing
       brackets in reverse nesting order.

    Anything else is left alone so that a genuinely wrong answer still fails
    loudly instead of being half-salvaged.
    """
    fixed = re.sub(r",(\s*[}\]])", r"\1", text)

    stack: list[str] = []
    in_string = False
    escaped = False
    for char in fixed:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack:
                stack.pop()

    if in_string:
        fixed += '"'
    for opener in reversed(stack):
        fixed += "]" if opener == "[" else "}"
    return fixed


class LLMClient:
    """Thin wrapper over an OpenAI-compatible chat completion endpoint."""

    def __init__(self, config: LLMConfig | None = None, force_mock: bool = False) -> None:
        self.config = config or LLMConfig()
        self.mock = force_mock or self.config.provider == "mock"
        self._client = None
        # Filled in after every network call so the benchmark can report
        # token cost and latency alongside the quality metrics.
        self.last_usage: dict[str, Any] = {}
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
    def generate_slides(self, constraints: UnitConstraints, mode: str = "full") -> dict[str, Any]:
        if self.mock:
            self.last_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_tokens": 0,
                "latency_s": 0.0,
                "model": "mock",
            }
            return self._mock_payload(constraints, mode)

        prompt = _build_prompt(constraints, mode)
        started = time.monotonic()
        base = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        raw = self._chat(base)
        self.last_usage["latency_s"] = round(time.monotonic() - started, 2)
        self.last_usage["model"] = self.config.model
        return self._parse(raw)

    # ------------------------------------------------------------ private
    def _chat(self, messages: list[dict[str, str]]) -> str:
        """Call the model and return an object that parses as slide JSON.

        ``response_format={"type": "json_object"}`` is not a validity
        guarantee.  Observed failure modes on DeepSeek, both of them in
        ordinary use:

        * the whole reply arrives as whitespace with ``finish_reason ==
          "stop"`` (non-JSON fragments are replaced by blanks);
        * the JSON is well-formed except for a trailing comma before ``]`` --
          seen roughly once per dozen calls.

        So the loop is: call -> light repair -> parse; and only if that still
        fails, ask again with the concrete error quoted back.  Retrying blind
        would burn the same tokens to land on the same mistake.
        """
        assert self._client is not None
        history = list(messages)
        base = list(messages)
        last_error = "模型返回空内容"
        extra_body = (
            {"thinking": {"type": "disabled"}}
            if self.config.thinking == "disabled"
            else None
        )

        for attempt in range(self.config.max_retries + 1):
            response = self._client.chat.completions.create(
                model=self.config.model,
                messages=history,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"},
                extra_body=extra_body,
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                details = getattr(usage, "completion_tokens_details", None)
                self.last_usage = {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "reasoning_tokens": getattr(details, "reasoning_tokens", 0) or 0,
                    "attempts": attempt + 1,
                }
            content = response.choices[0].message.content or ""

            if content.strip():
                try:
                    self._loads(content)
                    return content
                except LLMError as exc:
                    last_error = f"第 {attempt + 1} 次输出无法解析：{exc}"
            else:
                last_error = (
                    f"模型返回空内容（第 {attempt + 1} 次尝试）。"
                    "JSON 模式下非法输出会被替换为空格，通常是提示词约束不足。"
                )

            history = base + [
                {
                    "role": "user",
                    "content": "上一次的输出无法解析为 JSON。错误信息："
                    f"{last_error}\n请重新输出，只返回一个合法 JSON 对象，"
                    "以 { 开头、以 } 结尾；数组最后一个元素后不要加逗号；"
                    "不要任何解释文字或代码块标记。",
                }
            ]

        raise LLMError(last_error)

    @staticmethod
    def _loads(raw: str) -> dict[str, Any]:
        """Parse slide JSON, tolerating the two defects seen in the wild."""
        text = _strip_code_fence(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            repaired = _repair_json(text)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as exc:
                raise LLMError(f"{exc}（已尝试修复尾逗号与截断）") from exc

    def _parse(self, raw: str) -> dict[str, Any]:
        payload = self._loads(raw)
        if "slides" not in payload or not isinstance(payload["slides"], list):
            raise LLMError("返回 JSON 缺少 slides 数组")
        return payload

    # --------------------------------------------------------------- mock
    def _mock_payload(self, c: UnitConstraints, mode: str = "full") -> dict[str, Any]:
        """Deterministic offline output used for tests and demos.

        It deliberately degrades with the condition, mirroring what a weaker
        prompt actually does: no misconception page without the misconception
        block, and fewer concepts without the coverage list.  A mock that
        returned identical output for every condition would make the offline
        demo look like a rigged comparison.
        """
        has_misconception = mode in ("full", "no_order", "no_forbidden")
        concepts = list(c.required)
        if mode in ("rag", "rag_mc", "placebo", "cot", "zero_shot"):
            concepts = concepts[:-1] if len(concepts) > 2 else concepts
        if mode in ("placebo", "cot", "zero_shot"):
            concepts = concepts[:-1] if len(concepts) > 2 else concepts
        if mode == "no_misconception":
            has_misconception = False

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
                "bullets": [f"掌握 {n['name']}" for n in concepts[:4]],
                "code": "",
                "notes": "先明确本讲要解决的问题，再逐层展开。",
                "concept_ids": [],
                "background": False,
            }
        )

        concept_slides = max(c.slide_budget - 3, 1)
        buckets = self._chunk(concepts, concept_slides)
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

        for mc in (c.misconceptions[:2] if has_misconception else []):
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
                "bullets": [f"{n['name']}" for n in concepts[:4]],
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
