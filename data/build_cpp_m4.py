"""Build the second-course graph: C++ 语言, 第4章 数组.

Source of every concept, difficulty and misconception is the course team's own
lesson plan for the session, not the model's imagination:

    ~/Desktop/0502019-刘素行-教案/2025-2026-2学期-教案-刘素行/
        C++语言教案/C++语言教案-分章/第4章 数组.docx
        C++语言教案/ppt/C++课件/4-数组.pptx

The lesson plan names the 重点 (definition and subscript access; arrays as
function arguments; sorting and searching) and the 难点 (the harm of an
out-of-range subscript; the address semantics of an array name; two-dimensional
traversal and the '\\0' terminator), and its 教学反思 records two observed
failure modes verbatim: double-loop boundary errors in bubble sort, and students
ignoring the string terminator.  The three misconceptions below come from those
two lists.

Provenance differs from the Python course in one way that the paper states:
the Python misconceptions are backed by exam error rates, these are backed by
the lesson plan's own difficulty list and reflection.  They are still
instructor-authored observations about a real cohort, but they are not
quantified, and the `evidence` field says so rather than inventing a percentage.

Run:  python data/build_cpp_m4.py   (writes data/kg_cpp_m4.json)
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "kg_cpp_m4.json"

SOURCE = "第4章 数组教案（2025-2026-2，第2周第5次，24动漫制作技术4班）"


def concept(cid, name, definition, importance, aliases):
    return {
        "id": cid,
        "type": "Concept",
        "name": name,
        "definition": definition,
        "importance": importance,
        "aliases": aliases,
    }


def appears(cid, unit, seq):
    return {"type": "appears_in", "source": cid, "target": unit, "sequence": seq}


def prereq(src, dst, evidence):
    return {
        "type": "prerequisites_for",
        "source": src,
        "target": dst,
        "strength": "强依赖",
        "evidence": evidence,
    }


nodes = [
    {
        "id": "COURSE-CPP",
        "type": "Course",
        "name": "C++语言",
        "total_hours": 48,
        "major": "动漫制作技术",
        "level": "higher_vocational",
    },
    {
        "id": "M4CPP",
        "type": "Module",
        "name": "数组",
        "order": 4,
        "hours": 8,
        "objective": "掌握一维与二维数组的定义、初始化与下标访问，理解数组的连续存储与地址传递语义，"
        "能用数组完成排序与查找，并能说明越界与字符串结束标志的后果",
    },
    {
        "id": "U41",
        "type": "Unit",
        "name": "一维数组与字符数组",
        "order": 5,
        "hours": 4,
        "slide_budget": 6,
        "objective": "能定义并初始化一维数组，用从 0 开始的下标访问元素，说明越界的后果，"
        "并处理字符数组的字符串结束标志",
        "forbidden_terms": ["动态内存分配", "vector 容器", "指针算术", "快速排序", "归并排序"],
    },
    {
        "id": "U42",
        "type": "Unit",
        "name": "数组作函数参数与排序查找",
        "order": 6,
        "hours": 4,
        "slide_budget": 6,
        "objective": "能解释数组名作函数参数时的地址传递，写出冒泡排序并在有序数组上实现二分查找",
        "forbidden_terms": ["递归", "快速排序", "归并排序", "std::sort", "哈希表"],
    },
    # ---- U41 concepts
    concept(
        "C4101",
        "数组的定义与连续存储",
        "数组是一组同类型元素的连续存储，数组名代表首元素地址，元素在内存中依次排列",
        "理解",
        ["数组定义", "连续存储", "int a[10]"],
    ),
    concept(
        "C4102",
        "一维数组的初始化",
        "可在定义时全部初始化、部分初始化（其余补 0）或省略长度由初值个数决定",
        "掌握",
        ["数组初始化", "部分初始化", "省略长度"],
    ),
    concept(
        "C4103",
        "下标访问与从 0 开始",
        "数组元素用 a[i] 访问，下标从 0 开始，合法范围是 0 到 长度-1",
        "掌握",
        ["下标", "a[0]", "索引从0开始"],
    ),
    concept(
        "C4104",
        "下标越界的危害",
        "越界访问不会报错，会读写相邻内存，可能覆盖其他变量或触发运行时崩溃",
        "理解",
        ["越界", "数组越界", "off-by-one"],
    ),
    concept(
        "C4105",
        "字符数组与字符串",
        "字符数组存放字符序列；以 '\\0' 结尾的字符数组才构成 C 风格字符串",
        "掌握",
        ["字符数组", "char 数组", "字符串"],
    ),
    concept(
        "C4106",
        "字符串结束标志 '\\0'",
        "字符串以 '\\0' 作为结束标志，所有按字符串处理的函数都靠它判断结尾",
        "掌握",
        ["'\\0'", "结束标志", "空字符"],
    ),
    concept(
        "C4107",
        "strlen 与 sizeof 的区别",
        "strlen 数到 '\\0' 为止的字符个数，sizeof 给出数组占用的字节数（含 '\\0'）",
        "理解",
        ["strlen", "sizeof", "长度与容量"],
    ),
    # ---- U42 concepts
    concept(
        "C4201",
        "数组名作为函数参数",
        "数组名作实参会退化为指向首元素的指针，形参是地址的副本，对元素的修改作用于原数组",
        "掌握",
        ["数组传参", "地址传递", "退化为指针"],
    ),
    concept(
        "C4202",
        "数组长度的传递",
        "形参中无法用 sizeof 求得数组长度，必须由调用方把长度作为另一个参数传入",
        "掌握",
        ["传长度", "长度参数", "sizeof 失效"],
    ),
    concept(
        "C4203",
        "冒泡排序",
        "相邻元素两两比较并交换，每轮把当前最大值送到末尾，n 个元素最多 n-1 轮",
        "掌握",
        ["bubble sort", "冒泡", "相邻交换"],
    ),
    concept(
        "C4204",
        "二分查找及其有序前提",
        "在有序数组上反复比较中点并折半收缩区间，时间复杂度 O(log n)，前提是数组有序",
        "掌握",
        ["折半查找", "binary search", "有序前提"],
    ),
    concept(
        "C4205",
        "二维数组的定义与行列遍历",
        "二维数组按行优先存储，用双重循环按行、按列遍历，a[i][j] 中 i 为行、j 为列",
        "理解",
        ["二维数组", "行列遍历", "按行优先"],
    ),
    # ---- skills / lab / exercises
    {
        "id": "S4101",
        "type": "Skill",
        "name": "用一维数组统计成绩",
        "description": "输入 10 个成绩存入数组，输出平均分、最高分与最低分，并按下标从 0 开始访问",
        "importance": "熟练",
        "verifiable": True,
        "aliases": ["统计成绩", "求最高分", "求平均分"],
    },
    {
        "id": "S4201",
        "type": "Skill",
        "name": "实现冒泡排序",
        "description": "写出双重循环的冒泡排序并正确设定边界，对 10 个整数升序排序后输出",
        "importance": "熟练",
        "verifiable": True,
        "aliases": ["写冒泡排序", "双重循环排序", "升序排序"],
    },
    {
        "id": "L41",
        "type": "Lab",
        "name": "数组与排序上机实验",
        "objective": "完成成绩统计与冒泡排序两个任务，并用越界用例观察未定义行为",
        "instruments": ["g++ 13", "Visual Studio Code"],
        "steps": [
            "读入 10 个成绩到 int 数组，输出平均分、最高分、最低分",
            "实现冒泡排序并输出升序结果，打印每轮结束后的数组",
            "把循环条件故意写成 i <= n，观察输出异常并记录现象",
        ],
        "expected_output": "排序结果升序且每轮末尾元素就位；越界版本出现乱码或结果被破坏",
        "difficulty": 2,
    },
    {
        "id": "EX41",
        "type": "Exercise",
        "name": "数组下标范围选择题",
        "type_detail": "选择题",
        "difficulty": 1,
        "answer": "C（a[5] 越界，合法下标为 0..4）",
        "source": "第4章教案 课堂练习",
    },
    {
        "id": "EX42",
        "type": "Exercise",
        "name": "冒泡排序轮数与比较次数填空",
        "type_detail": "填空题",
        "difficulty": 2,
        "answer": "n 个元素最多 n-1 轮；第 i 轮比较 n-i 次",
        "source": "第4章教案 课堂练习",
    },
    {
        "id": "EX43",
        "type": "Exercise",
        "name": "数组传参为何还要传长度简答",
        "type_detail": "简答题",
        "difficulty": 2,
        "answer": "形参中的数组名已退化为指针，sizeof 得到的是指针大小而非数组长度，故须另传长度",
        "source": "第4章教案 教学难点",
    },
    {
        "id": "EX44",
        "type": "Exercise",
        "name": "sizeof 与 strlen 结果填空",
        "type_detail": "填空题",
        "difficulty": 2,
        "answer": "char s[] = \"hello\" 时 sizeof(s) 为 6，strlen(s) 为 5",
        "source": "第4章教案 教学反思（结束标志为薄弱环节）",
    },
    # ---- misconceptions (see module docstring for provenance)
    {
        "id": "MC41",
        "type": "Misconception",
        "statement": "C++ 数组下标从 1 开始，a[1] 才是第一个元素",
        "correction": "下标从 0 开始，第一个元素是 a[0]，最后一个合法下标是 长度-1；按 1 起访问会整体错位并在末尾越界",
        "frequency": "中频",
        "evidence": "第4章教案「教学重难点」明确列出“下标从 0 开始与越界的危害”；未量化错误率",
    },
    {
        "id": "MC42",
        "type": "Misconception",
        "statement": "字符数组就是字符串，遍历到数组长度就行，不必管 '\\0'",
        "correction": "只有以 '\\0' 结尾的字符数组才是字符串；按数组长度遍历会把结束标志之后的未初始化字节当字符输出，strlen 数到 '\\0' 为止而 sizeof 计全部字节",
        "frequency": "高频",
        "evidence": "第4章教案「教学反思」原文：“字符数组与字符串处理是薄弱环节，学生容易忽略结束标志”",
    },
    {
        "id": "MC43",
        "type": "Misconception",
        "statement": "数组作函数参数是值传递，函数里改了形参也不影响实参",
        "correction": "数组名作实参会退化为指向首元素的指针，形参拿到的是地址副本，对元素的修改作用于原数组；但形参上 sizeof 求不到长度，所以必须另传长度",
        "frequency": "中频",
        "evidence": "第4章教案「教学重难点」列出“数组名作为地址传递的本质”；未量化错误率",
    },
]


edges = [
    {"type": "is_part_of", "source": "M4CPP", "target": "COURSE-CPP"},
    {"type": "is_part_of", "source": "U41", "target": "M4CPP"},
    {"type": "is_part_of", "source": "U42", "target": "M4CPP"},
]

# appears_in: sequence is the topological position inside the session
for seq, cid in enumerate(
    ["C4101", "C4102", "C4103", "C4104", "C4105", "C4106", "C4107"], start=1
):
    edges.append(appears(cid, "U41", seq))
for seq, cid in enumerate(["C4201", "C4202", "C4203", "C4204", "C4205"], start=1):
    edges.append(appears(cid, "U42", seq))
edges += [
    appears("S4101", "U41", 8),
    appears("S4201", "U42", 6),
    appears("L41", "U41", 9),
    appears("EX41", "U41", 10),
    appears("EX44", "U41", 11),
    appears("EX42", "U42", 7),
    appears("EX43", "U42", 8),
    appears("MC41", "U41", 12),
    appears("MC42", "U41", 13),
    appears("MC43", "U42", 9),
]

edges += [
    prereq("C4101", "C4102", f"{SOURCE}：先有定义与存储模型，才谈初始化"),
    prereq("C4102", "C4103", f"{SOURCE}：初始化后按下标逐个访问"),
    prereq("C4103", "C4104", f"{SOURCE}：知道合法范围才能理解越界"),
    prereq("C4101", "C4105", f"{SOURCE}：字符数组是元素类型为 char 的数组"),
    prereq("C4105", "C4106", f"{SOURCE}：字符串的判定依赖结束标志"),
    prereq("C4106", "C4107", f"{SOURCE}：strlen 停在 '\\0'，sizeof 计全部字节"),
    prereq("C4103", "C4201", f"{SOURCE}：传参本质是传首元素地址，需先懂下标与地址"),
    prereq("C4201", "C4202", f"{SOURCE}：形参退化后 sizeof 失效，故须传长度"),
    prereq("C4203", "C4204", f"{SOURCE}：二分查找要求数组有序，排序是其前提"),
    {"type": "is_a", "source": "C4105", "target": "C4101", "evidence": f"{SOURCE}：字符数组是数组的特例"},
    {
        "type": "relates_to",
        "source": "C4106",
        "target": "C4107",
        "relation": "对照",
        "evidence": f"{SOURCE}：结束标志与长度计算是一对易混概念",
    },
    {
        "type": "relates_to",
        "source": "C4203",
        "target": "C4204",
        "relation": "对照",
        "evidence": f"{SOURCE}：排序为查找准备前提，两者常同堂讲授",
    },
    {
        "type": "implements",
        "source": "S4201",
        "target": "C4203",
        "language": "C++",
        "api": ["for", "if", "swap"],
        "evidence": f"{SOURCE} 实践任务：写出双重循环冒泡排序",
    },
    {
        "type": "implements",
        "source": "S4101",
        "target": "C4103",
        "language": "C++",
        "api": ["int[]", "for"],
        "evidence": f"{SOURCE} 实践任务 1：用下标遍历统计成绩",
    },
    {"type": "verified_by", "source": "S4201", "target": "L41", "evidence": f"{SOURCE} 上机任务"},
    {"type": "verified_by", "source": "S4101", "target": "L41", "evidence": f"{SOURCE} 上机任务"},
    {"type": "assessed_by", "source": "C4103", "target": "EX41", "weight": 0.05},
    {"type": "assessed_by", "source": "C4203", "target": "EX42", "weight": 0.05},
    {"type": "assessed_by", "source": "C4201", "target": "EX43", "weight": 0.05},
    {"type": "assessed_by", "source": "C4106", "target": "EX44", "weight": 0.05},
    # misconception targeting: the unit owns the correction, the concept gives
    # the slide its anchor
    {"type": "addresses_misconception", "source": "U41", "target": "MC41", "strategy": "反例对比"},
    {"type": "addresses_misconception", "source": "C4103", "target": "MC41", "strategy": "代码演示"},
    {"type": "addresses_misconception", "source": "U41", "target": "MC42", "strategy": "边界测试"},
    {"type": "addresses_misconception", "source": "C4106", "target": "MC42", "strategy": "代码演示"},
    {"type": "addresses_misconception", "source": "U42", "target": "MC43", "strategy": "反例对比"},
    {"type": "addresses_misconception", "source": "C4201", "target": "MC43", "strategy": "代码演示"},
]

graph = {
    "meta": {
        "schema_version": "0.1",
        "course_id": "CPP-2026",
        "course_name": "C++语言",
        "module_scope": "第4章 数组",
        "language": "C++",
        "generated_for": "second-course replication (course-boundary check)",
        "schema_ref": "../kg-design/schema.yaml",
        "source": SOURCE,
    },
    "nodes": nodes,
    "edges": edges,
}

if __name__ == "__main__":
    OUT.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}  nodes={len(nodes)} edges={len(edges)}")
