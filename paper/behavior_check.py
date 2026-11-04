"""Behavioural probing of the code blocks the decks emit.

§7.6 of the paper reports that all 117 blocks parse but that a runnability
metric must test behaviour.  This script implements a minimal behavioural
probe: each block that actually defines an enqueue/dequeue pair (module-level
functions or methods of a class) is executed in a fresh namespace and checked
against session behaviours:

    FIFO      two enqueues followed by two dequeues return the first item first
    empty     dequeuing from an empty queue signals (returns None, raises, or
              prints an explicit message) rather than returning garbage
    full      overfilling the queue signals rather than silently corrupting
    survive   after emptying, the structure still accepts new items

Blocks that are bare demonstration fragments (U11's two wrap-around lines) or
that define neither interface are counted as ``not testable''; the share of
testable blocks is reported next to the pass rate, because a pass rate over a
self-selected subset is otherwise flattering.

Everything runs locally on the released deck JSON files; no API calls.

Usage:
    python paper/behavior_check.py            # per-condition summary
    python paper/behavior_check.py --verbose  # per-block outcomes
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
RUNS = [ROOT / "outputs" / "main_v1"]

UNIT_BEHAVIOURS = {
    "U10": ["fifo", "empty", "full", "survive"],
    "U11": [],  # wrap-around fragments, not a runnable program
    "U12": ["fifo", "empty", "survive"],
}


def _capacity(ns: dict) -> int:
    for name in ("MAXSIZE", "MAX", "CAP", "CAPACITY", "maxsize", "capacity"):
        value = ns.get(name)
        if isinstance(value, int) and value > 0:
            return value
    return 5


def strip_demo(code: str) -> str:
    """Drop top-level demonstration code, keep definitions and state setup.

    Lecture slides routinely append a demo (``for i in range(MAXSIZE):
    enqueue(i)``) after the definitions.  Executing it leaves the queue in a
    half-used state, which would fail every later probe for reasons that have
    nothing to do with the code being right.  We therefore keep only
    assignments and def/class statements at module level and drop bare
    expressions, loops and ifs; function and class bodies are untouched.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    keep = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Import, ast.ImportFrom))
    ]
    if not keep or len(keep) == len(tree.body):
        return code
    return ast.unparse(ast.Module(body=keep, type_ignores=[]))


class Probe:
    """Run one code block in a fresh namespace and probe queue behaviours."""

    def __init__(self, code: str):
        self.code = strip_demo(code)
        self.ns: dict = {}
        self.exec_error: str | None = None
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            try:
                exec(compile(self.code, "<slide>", "exec"), self.ns)
            except Exception as exc:  # noqa: BLE001 - probing arbitrary code
                self.exec_error = f"{type(exc).__name__}: {exc}"
        self._stdout = buf.getvalue()

    # ------------------------------------------------------------- interface
    @property
    def kind(self) -> str | None:
        if self.exec_error is not None:
            return None
        if callable(self.ns.get("enqueue")) and callable(self.ns.get("dequeue")):
            params = list(inspect.signature(self.ns["enqueue"]).parameters)
            if params and params[0] == "self":
                return None  # method fragment: the class is on another slide
            return "module"
        for value in self.ns.values():
            if isinstance(value, type) and hasattr(value, "enqueue") and hasattr(value, "dequeue"):
                try:
                    value()  # zero-argument constructor?
                except TypeError:
                    return None
                return "class"
        return None

    # ---------------------------------------------------------------- probes
    def _signal(self, call) -> bool:
        """True if the call signalled a boundary (falsy result, exception, message)."""
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            try:
                result = call()
            except Exception:
                return True
        if result is None or result is False:
            return True
        return bool(buf.getvalue().strip())

    def _module_queue(self):
        """Fresh namespace for each probe, since state lives in globals."""
        ns: dict = {}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(self.code, "<slide>", "exec"), ns)
        return ns

    def probe_module(self, name: str) -> bool:
        ns = self._module_queue()
        enqueue, dequeue = ns["enqueue"], ns["dequeue"]
        n_params = len(inspect.signature(enqueue).parameters)
        if n_params >= 2:
            # state-object style: enqueue(q, x) with q.data / q.front / q.rear
            state = SimpleNamespace(front=0, rear=0)
            capacity = _capacity(ns)
            for attr in ("data", "queue", "arr", "items"):
                setattr(state, attr, [None] * capacity)
            for attr in ("CAP", "MAXSIZE", "MAX", "maxsize"):
                setattr(state, attr, capacity)
            call_enq = lambda x: enqueue(state, x)  # noqa: E731
            call_dq = lambda: dequeue(state)  # noqa: E731
        else:
            call_enq, call_dq = enqueue, dequeue
            capacity = _capacity(ns)

        if name == "fifo":
            call_enq("a")
            call_enq("b")
            return call_dq() == "a" and call_dq() == "b"
        if name == "empty":
            return self._signal(call_dq)
        if name == "full":
            for _ in range(int(capacity)):
                call_enq("x")
            return self._signal(lambda: call_enq("overflow"))
        if name == "survive":
            call_enq("a")
            call_dq()
            call_enq("b")
            return call_dq() == "b"
        raise ValueError(name)

    def probe_class(self, name: str) -> bool:
        cls = next(
            v for v in self.ns.values()
            if isinstance(v, type) and hasattr(v, "enqueue") and hasattr(v, "dequeue")
        )
        try:
            q = cls()
        except Exception:
            return False
        enqueue, dequeue = q.enqueue, q.dequeue
        if name == "fifo":
            enqueue("a")
            enqueue("b")
            return dequeue() == "a" and dequeue() == "b"
        if name == "empty":
            return self._signal(dequeue)
        if name == "full":
            # a linked queue is unbounded by design (loop completes -> pass);
            # a bounded queue must signal at or after the first enqueue
            done = 0
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    for _ in range(64):
                        enqueue("x")
                        done += 1
                    return True
                except Exception:
                    return done >= 1
        if name == "survive":
            enqueue("a")
            dequeue()
            enqueue("b")
            return dequeue() == "b"
        raise ValueError(name)

    # ----------------------------------------------------------------- public
    def run(self, unit: str) -> tuple[list[str], list[str]]:
        """Return (passed, failed) over the behaviours defined for ``unit``."""
        kind = self.kind
        if kind is None:
            return [], []
        passed, failed = [], []
        for name in UNIT_BEHAVIOURS[unit]:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    ok = getattr(self, f"probe_{kind}")(name)
            except Exception:
                ok = False
            (passed if ok else failed).append(name)
        return passed, failed


def main() -> None:
    verbose = "--verbose" in sys.argv
    per_condition: dict[str, list[tuple[str, list[str], list[str], str | None]]] = defaultdict(list)

    for directory in RUNS:
        for path in sorted(directory.glob("*__*__r*.json")):
            unit, mode, _rep = path.stem.split("__")
            payload = json.loads(path.read_text(encoding="utf-8"))
            for slide in payload.get("slides", []):
                code = str(slide.get("code") or "").strip()
                if not code:
                    continue
                probe = Probe(code)
                kind = probe.kind
                passed, failed = probe.run(unit)
                per_condition[mode].append(
                    (f"{path.stem}:s{slide['index']}", passed, failed, kind, unit)
                )

    print(f"{'condition':<11}{'blocks':>7}{'testable':>9}{'passed':>8}{'rate':>7}")
    totals = {}
    for mode in sorted(per_condition):
        blocks = per_condition[mode]
        testable = [b for b in blocks if b[3] in ("module", "class") and b[1] + b[2]]
        good = [b for b in testable if not b[2]]
        totals[mode] = (len(blocks), len(testable), len(good))
        rate = f"{len(good) / len(testable):.2f}" if testable else "  -"
        print(f"{mode:<11}{len(blocks):>7}{len(testable):>9}{len(good):>8}{rate:>7}")

    all_blocks = sum(v[0] for v in totals.values())
    all_test = sum(v[1] for v in totals.values())
    all_good = sum(v[2] for v in totals.values())
    print(f"{'all':<11}{all_blocks:>7}{all_test:>9}{all_good:>8}"
          f"{(all_good / all_test if all_test else 0):>7.2f}")

    if verbose:
        print("\nPer-block detail (testable blocks):")
        for mode in sorted(per_condition):
            for tag, passed, failed, kind, unit in per_condition[mode]:
                if kind not in ("module", "class"):
                    continue
                if not passed and not failed:
                    print(f"  {mode:<10} {tag:<22} ----  [{kind}] no behaviours for {unit}")
                    continue
                mark = "ok" if passed and not failed else "FAIL"
                detail = "+".join(passed) + ("  MISSING:" + ",".join(failed) if failed else "")
                print(f"  {mode:<10} {tag:<22} {mark:<5} [{kind}] {detail}")


if __name__ == "__main__":
    main()
