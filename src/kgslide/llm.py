"""LLM access layer with a deterministic offline mock.

Three providers are supported, all behind the same OpenAI-compatible surface:

* ``deepseek`` -- ``https://api.deepseek.com``, the backbone used for the main
                  comparison, the ablations and the stylometric checks.
* ``kimi``     -- ``https://api.moonshot.cn/v1``, a second model family used
                  only for the cross-model check: if a structural effect also
                  appears under a different vendor's prompt tuning, it cannot
                  be an artefact of one model's idiosyncrasies.
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
from pathlib import Path
from typing import Any

from .constraints import UnitConstraints


def load_dotenv(path: Path | None = None) -> None:
    """Load ``KEY=VALUE`` pairs from ``.env`` into the environment.

    ``.env.example`` has always told the user to copy it to ``.env``, but
    nothing read the file, so a freshly cloned repo failed with "the environment
    variable is not set" even after the key was filled in.  Done here rather than in a dependency:
    the format needed is three lines of ``str.partition``.

    Existing environment variables win, so an explicit ``export`` (or a CI
    secret) is never silently overridden by a stale local file.
    """
    env_path = path or Path.cwd() / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

SYSTEM_PROMPT = """你是一位高职院校计算机专业教师，正在制作课件。
输出必须是合法 JSON，不要包裹在 Markdown 代码块中，不要输出任何解释性文字。"""

def json_spec(code_lang: str = "Python") -> str:
    """Output contract, with the code language of the course substituted in.

    The first course is a Python one and the spec was written for it; a second
    course in C++ would otherwise be asked for Python snippets, which is a
    silent cross-course confound rather than a formatting detail.
    """
    # ``str.format`` cannot be used: the spec is full of literal JSON braces.
    return _JSON_SPEC.replace("{code_lang}", code_lang)


_JSON_SPEC = """## 输出格式（Output a single valid JSON object）
{
  "unit_id": "...",
  "slides": [
    {
      "index": 1,
      "layout": "title|objectives|concept|comparison|code|misconception|summary",
      "title": "页面标题，不超过 20 字",
      "bullets": ["要点1", "要点2", "要点3"],
      "code": "可选的 {code_lang} 代码片段，没有则留空字符串",
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
    spec = json_spec(getattr(c, "language", "Python") or "Python")
    head = f"请为高职《{course}》课程第 {c.unit_order} 讲「{c.unit_name}」制作一份课件。"

    if mode == "full":
        return (
            f"请根据以下约束生成课件。\n\n{c.to_prompt_block()}\n\n"
            f"{spec}\n\n{RULES_CONSTRAINED.format(slide_budget=c.slide_budget)}"
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
            f"{spec}\n\n{rules.format(slide_budget=c.slide_budget)}"
        )

    if mode == "zero_shot":
        return f"{head}\n\n{spec}\n\n{RULES_BASELINE.format(slide_budget=c.slide_budget)}"
    if mode == "rag":
        fragments = "\n".join(
            f"- {n['name']}：{n['definition']}" for n in c.required + c.optional
        )
        return (
            f"{head}\n\n## 教材片段\n{fragments}\n\n{spec}\n\n"
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
            f"{spec}\n\n{RULES_BASELINE.format(slide_budget=c.slide_budget)}"
        )
    if mode == "cot":
        return (
            f"{head}\n\n{spec}\n\n"
            f"{RULES_BASELINE.format(slide_budget=c.slide_budget)}\n"
            "4. 先在每页 notes 中说明该页在整讲中的定位与前后衔接，再写页面内容。"
        )
    if mode == "placebo":
        # Same token budget as `full`, zero course-specific structure.  If the
        # constrained condition still wins here, the gain is knowledge, not
        # prompt length.
        base = f"{head}\n\n{spec}\n\n{RULES_BASELINE.format(slide_budget=c.slide_budget)}"
        target = len(_build_prompt(c, "full"))
        return _pad_to(base, target, PLACEBO_GUIDANCE)
    raise ValueError(f"unknown mode: {mode} (expected one of {', '.join(MODES)})")


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


@dataclass(frozen=True)
class ProviderPreset:
    """Connection defaults for one OpenAI-compatible vendor."""

    base_url: str
    api_key_env: str
    default_model: str
    # DeepSeek accepts a top-level ``thinking`` request field; other vendors
    # reject unknown fields, so it is sent only where it is understood.
    sends_thinking_field: bool = False
    # Some vendors pin sampling for their reasoning models.  Kimi K3 rejects any
    # temperature other than 1.0 with a 400, so the cross-model run is recorded
    # at 1.0 rather than silently failing or quietly staying at 0.3.
    fixed_temperature: float | None = None


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "deepseek": ProviderPreset(
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-v4-flash",
        sends_thinking_field=True,
    ),
    # Second backbone for the cross-model check: same OpenAI-compatible
    # surface, different model family, so a structural effect cannot be an
    # artefact of one vendor's prompt tuning.
    "kimi": ProviderPreset(
        base_url="https://api.moonshot.cn/v1",
        api_key_env="MOONSHOT_API_KEY",
        default_model="kimi-k3",
        fixed_temperature=1.0,
    ),
    # Third endpoint, used only for the second-course replication: the official
    # DeepSeek key was out of balance on the day of the run, and a course
    # replication that changes the course must hold the *design* fixed rather
    # than wait.  Recorded in results.csv like any other backbone, and never
    # merged with the main table.
    "agnes": ProviderPreset(
        base_url="https://apihub.agnes-ai.com/v1",
        api_key_env="AGNES_API_KEY",
        default_model="agnes-2.5-flash",
    ),
    "mock": ProviderPreset(base_url="", api_key_env="", default_model="mock"),
}


@dataclass
class LLMConfig:
    provider: str = "deepseek"
    # Official DeepSeek API model ids (as of 2026-11).
    # deepseek-chat / deepseek-reasoner were deprecated on 2026-07-24 and now
    # only survive as compatibility aliases for v4-flash thinking modes.
    #
    # Empty strings mean "take the preset for this provider", so switching
    # vendors cannot silently inherit the previous vendor's model id or key.
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    temperature: float = 0.3
    max_tokens: int = 16000
    max_retries: int = 2
    # Vendor rate limits, not model errors: a 54-cell sweep on a low-tier
    # account returns "please try again after 1 seconds" often enough that
    # aborting the sweep on the first 429 wastes the run.  Retried with
    # exponential backoff and never counted as an attempt at the JSON level.
    max_rate_limit_retries: int = 5
    # "default" keeps the model's built-in thinking pass; "disabled" turns it
    # off.  Measurements on 2026-11 show deepseek-v4-flash emits reasoning
    # tokens by default, which would silently confound a chain-of-thought
    # baseline -- so the setting is recorded per run instead of assumed.
    thinking: str = "default"
    # Flipped off per instance when the endpoint rejects response_format; the
    # prompt already asks for bare JSON, so this is a compatibility fallback
    # rather than a change of experimental condition.
    json_mode: bool = True

    def __post_init__(self) -> None:
        preset = PROVIDER_PRESETS.get(self.provider)
        if preset is None:
            raise LLMError(
                f"unknown provider: {self.provider} "
                f"(expected one of {', '.join(PROVIDER_PRESETS)})"
            )
        if not self.model:
            self.model = preset.default_model
        if not self.base_url:
            self.base_url = preset.base_url
        if not self.api_key_env:
            self.api_key_env = preset.api_key_env
        if preset.fixed_temperature is not None:
            self.temperature = preset.fixed_temperature


class LLMError(RuntimeError):
    """Raised when the model returns something unusable."""


def _is_rate_limited(exc: BaseException) -> bool:
    """True if ``exc`` is the vendor asking us to slow down."""
    if getattr(exc, "status_code", None) == 429:
        return True
    text = str(exc).lower()
    return "rate limit" in text or "429" in text or "too many requests" in text


def _suggested_wait(exc: BaseException, default: float) -> float:
    """Honour "please try again after N seconds" when the vendor says it."""
    match = re.search(r"after (\d+(?:\.\d+)?) seconds", str(exc))
    return max(float(match.group(1)), 1.0) if match else default


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
            load_dotenv()
            api_key = os.environ.get(self.config.api_key_env, "")
            if not api_key:
                raise LLMError(
                    f"environment variable {self.config.api_key_env} is not set. "
                    "Set it and retry, or use --mock for an offline demo."
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

    def repair_slides(
        self, constraints: UnitConstraints, mode: str, feedback: str
    ) -> dict[str, Any]:
        """Regenerate a deck that failed acceptance, with the findings attached.

        The prompt is the *same* condition prompt, with the validator's findings
        appended: nothing the model was not already given is added, so the
        repair loop cannot smuggle in a constraint that the condition withheld.
        That is why this is only meaningful for a condition whose prompt already
        contains the requirement being reported -- see ``paper/repair_loop.py``.

        The findings are stated as what failed, not as what to write: the output
        format, page budget and rules are unchanged, and the model still has to
        produce a whole deck.
        """
        if self.mock:
            self.last_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_tokens": 0,
                "latency_s": 0.0,
                "model": "mock",
            }
            return self._mock_payload(constraints, mode)

        prompt = (
            f"{_build_prompt(constraints, mode)}\n\n"
            f"## 上一版课件未通过自动验收\n{feedback}\n\n"
            "请针对以上问题重做整套课件。除这些问题之外的所有要求保持不变，"
            "页数与输出格式与上次相同，仍然只返回 JSON 对象本身。"
        )
        started = time.monotonic()
        raw = self._chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
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
        preset = PROVIDER_PRESETS[self.config.provider]
        extra_body = (
            {"thinking": {"type": "disabled"}}
            if self.config.thinking == "disabled" and preset.sends_thinking_field
            else None
        )

        for attempt in range(self.config.max_retries + 1):
            response = self._create(history, extra_body)
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

    def _create(self, messages: list[dict[str, str]], extra_body: dict | None):
        """One completion call, with a compatibility fallback for JSON mode.

        Some OpenAI-compatible endpoints (and proxies in front of them) reject
        ``response_format`` outright with a 400.  The prompt already demands a
        bare JSON object, so dropping the flag changes the transport, not the
        experimental condition; the fallback is remembered so it costs one
        rejected request per run instead of one per cell.
        """
        assert self._client is not None
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        if self.config.json_mode:
            try:
                return self._retry(
                    lambda: self._client.chat.completions.create(
                        response_format={"type": "json_object"}, **kwargs
                    )
                )
            except Exception as exc:  # noqa: BLE001 - vendor-specific 400
                if "response_format" not in str(exc).lower():
                    raise
                self.config.json_mode = False
        return self._retry(lambda: self._client.chat.completions.create(**kwargs))

    def _retry(self, call):
        """Run ``call``, backing off while the vendor says we are too fast.

        Kimi's low tier answers with ``429 rate_limit_reached_error`` and a
        suggested delay; treating that as a failure would truncate a sweep
        halfway and leave a results table with holes.
        """
        delay = 2.0
        for attempt in range(self.config.max_rate_limit_retries + 1):
            try:
                return call()
            except Exception as exc:  # noqa: BLE001 - vendor-specific status
                if not _is_rate_limited(exc) or attempt == self.config.max_rate_limit_retries:
                    raise
                wait = _suggested_wait(exc, default=delay)
                print(f"    rate limited, waiting {wait:.1f}s", flush=True)
                time.sleep(wait)
                delay = min(delay * 2, 60.0)

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
                raise LLMError(f"{exc} (after repairing trailing commas and truncation)") from exc

    def _parse(self, raw: str) -> dict[str, Any]:
        payload = self._loads(raw)
        if "slides" not in payload or not isinstance(payload["slides"], list):
            raise LLMError("the returned JSON has no slides array")
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
