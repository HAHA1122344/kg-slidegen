# kgslide · 知识图谱约束的课件生成

> 用课程知识图谱约束大模型生成课件，让每一页都有据可依、顺序讲得通、错误有人管。

大多数「AI 生成 PPT」的做法是把文档丢给模型，让它自由发挥。结果通常是：内容看着像，但漏掉关键知识点、顺序颠倒、把学生常见的错误又讲了一遍。

本项目换一个思路：**先把课程建成知识图谱，再让图谱约束生成**。

- 每个讲次生成哪几个概念，由图谱的 `appears_in` 和 `importance` 决定
- 讲解顺序由 `prerequisites_for` 的拓扑序强制约束，不会先讲队满再讲队空
- 学生的高频误区作为一等公民建模（`Misconception` 节点），生成时必须产出纠错内容
- 生成完自动回验，五个指标量化「讲没讲全、有没有跑题、顺序对不对」

## 效果示例

以高职《Python 数据结构》第 11 讲「循环队列」为例（离线 mock 模式）：

| 指标 | 值 | 含义 |
| --- | --- | --- |
| coverage_rate | 1.000 | 6 个必需概念全部覆盖 |
| oog_rate | 0.000 | 没有引入图谱外概念 |
| background_rate | 0.125 | 只在一处回顾了先修的「顺序队列」 |
| prerequisite_violation | 0.000 | 讲解顺序完全符合先修约束 |
| misconception_coverage | 1.000 | 「判空当判满」这个高频错误已被纠正 |
| editability | 1.000 | 全部为原生可编辑形状，无图片化文本 |

生成结果是一个可直接编辑的 `.pptx`（13.33×7.5，16:9），在 PowerPoint、Keynote、WPS 里都能改字改版。

## 安装

```bash
git clone <your-repo-url>
cd kg-slidegen
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

需要 Python 3.10+。

## 快速开始

### 1. 先看图谱长什么样

```bash
kgslide info
kgslide check-graph
```

`check-graph` 会跑结构校验：悬空边、先修成环、节点未锚定讲次、语义边缺证据、讲次概念数越界。

### 2. 查看某个讲次的生成约束

```bash
kgslide inspect --unit U11
```

输出就是这个讲次交给模型的完整契约：必须覆盖什么、按什么顺序、要纠正哪条误区、哪些概念只能一句话带过。

### 3. 离线跑通全流程（不花钱、不需要 key）

```bash
kgslide generate --unit U11 --mock
```

会在 `outputs/` 下生成 `U11.pptx` 并打印五个指标。mock 模式完全确定性，适合调试和写论文时的 baseline 对照。

### 4. 接入真实模型

```bash
export DEEPSEEK_API_KEY=sk-xxxxxxxx
kgslide generate --unit all --out outputs --summary outputs/summary.json
```

默认走 DeepSeek 的 OpenAI 兼容接口。换模型只需改 `--model` 或 `config/default.yaml` 里的 `base_url`。

## 图谱结构

`data/kg_pyds_m4.json` 是 M4「队列」模块的完整图谱（33 节点 / 72 边），格式遵循 `schema.yaml`。

**7 类节点**：`Course` · `Module` · `Unit` · `Concept` · `Skill` · `Lab` · `Exercise` · `Misconception`

Schema 沿用 [K12-KGraph](https://github.com/haolpku/K12-KGraph)（NeurIPS 2026 Evaluations & Datasets Track），并扩展三处：

| 扩展 | 理由 |
| --- | --- |
| `Misconception` 节点 | 职教场景下纠错比讲授更有效，原 schema 无法表达这一教学要素 |
| `implements` 边（概念→代码） | 编程课的知识落点是代码，需显式建模，并用于检查生成内容的可执行性 |
| `addresses_misconception` 边 | 让图谱能约束生成器产出针对性纠错内容 |

**10 类边**：`is_a` · `prerequisites_for` · `relates_to` · `implements` · `verified_by` · `assessed_by` · `addresses_misconception` · `appears_in` · `is_part_of` · `leads_to`

## 工作流

```
单元子图 ──► 约束契约 ──► LLM 生成 ──► 渲染 pptx ──► 回验证
   │            │            │            │           │
 graph.py  constraints.py  llm.py    renderer.py  validator.py
```

关键设计：**约束是数据，不是提示词**。`UnitConstraints` 同时驱动生成和校验，保证「要求」和「验收」用的是同一份定义。

## 指标定义

| 指标 | 计算方式 |
| --- | --- |
| `coverage_rate` | 已覆盖的必需概念 / 必需概念总数 |
| `oog_rate` | 图谱外概念与禁用概念 / 总提及概念数 |
| `background_rate` | 作为回顾引用的兄弟讲次概念 / 总提及概念数（上限 20%） |
| `prerequisite_violation` | 违反拓扑序的概念对 / 概念对总数 |
| `misconception_coverage` | 已纠正的误区 / 该讲次关联的误区总数 |
| `editability` | 原生可编辑形状 / 全部形状 |

中文没有词边界，`队列` 会匹配到 `循环队列` 里。因此文本级检测使用 `_net_occurrences`：先统计原始出现次数，再扣除出现在更长术语内部的次数，避免虚高。

## 目录结构

```
kg-slidegen/
├── data/kg_pyds_m4.json      # 课程图谱（M4 队列模块）
├── src/kgslide/
│   ├── graph.py              # 加载、查询、DAG 校验、拓扑排序
│   ├── constraints.py        # 单元子图 → 生成契约
│   ├── llm.py                # DeepSeek 客户端 + 确定性 mock
│   ├── renderer.py           # python-pptx 渲染
│   ├── validator.py          # 五项指标回验
│   └── cli.py                # 命令行入口
├── tests/                    # 16 项测试
├── config/default.yaml
└── schema.yaml               # 形式化 schema 定义（见 kg-design/）
```

## 测试

```bash
pytest -q
```

覆盖：图谱结构合法性、环检测、拓扑序、约束切分、mock 渲染、指标边界、顺序违例与漏讲检测。

## 路线图

- [ ] 补齐 M1–M8 全部模块（当前只有 M4）
- [ ] 支持从教材 PDF 半自动建图（参考 SCI-MKG 的反向管线）
- [ ] 加入渲染回看闭环：截图 → VLM 检查溢出与重叠 → 自动修正
- [ ] 发布中文职教课件评测集，供同类工作横向对比

## 引用

如果你在论文中使用本项目，请引用：

```bibtex
@software{kgslide2026,
  title  = {kgslide: Knowledge-Graph-Constrained Courseware Generation},
  author = {Liu, Suxing},
  year   = {2026},
  url    = {https://github.com/<your-account>/kg-slidegen}
}
```

## License

MIT，见 [LICENSE](LICENSE)。
