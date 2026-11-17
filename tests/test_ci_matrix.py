import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import browser_results, ci_matrix
from tests.test_browser_results import fixture


class BrowserMatrixTests(unittest.TestCase):
    def setUp(self):
        self.plan = {"head": "a" * 40, "mode": "targeted", "e2e_specs": ["tests/e2e/a.spec.mjs", "tests/e2e/b.spec.mjs"]}

    def test_expansion_and_override(self):
        self.assertEqual(ci_matrix.shards(self.plan), 1)
        self.plan["e2e_specs"] = [str(n) for n in range(17)]
        self.assertEqual(ci_matrix.shards(self.plan), 2)
        self.assertEqual(ci_matrix.shards(self.plan, "3"), 3)
        self.assertEqual(ci_matrix.shards({**self.plan, "mode": "full"}), 4)
        with self.assertRaises(ValueError):
            ci_matrix.shards(self.plan, "5")

    def make_evidence(self, base):
        listed_a, actual_a = fixture("a.spec.mjs", "first")
        listed_b, actual_b = fixture("b.spec.mjs", "second")
        full = copy.deepcopy(listed_a)
        full["config"]["shard"] = None
        full["suites"].append(copy.deepcopy(listed_b["suites"][0]))
        roots = []
        for index, listed, actual in ((1, listed_a, actual_a), (2, listed_b, actual_b)):
            for report in (listed, actual):
                report["config"]["shard"] = {"current": index, "total": 2}
            root = Path(base) / str(index)
            root.mkdir()
            summary = {"shard": {"current": index, "total": 2}, "head": self.plan["head"],
                       "selection_fingerprint": ci_matrix.fingerprint(self.plan), "exit_code": 0,
                       "requested_layer": "browser"}
            files = {"summary.json": summary, "browser-regressions-full.json": full,
                     "browser-regressions-list.json": listed, "browser-regressions.json": actual,
                     "browser-regressions-validated.json": browser_results.validate(listed, actual, index, 2)}
            for name, value in files.items():
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            roots.append(root)
        return roots

    def test_gate_accepts_complete_discovery_and_rejects_missing_or_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = self.make_evidence(tmp)
            ci_matrix.gate(self.plan, 2, roots)
            with self.assertRaises(ValueError):
                ci_matrix.gate(self.plan, 2, roots[:1])
            report = roots[1] / "browser-regressions.json"
            value = json.loads(report.read_text(encoding="utf-8"))
            value["suites"][0]["specs"][0]["tests"][0]["results"][0]["status"] = "failed"
            report.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                ci_matrix.gate(self.plan, 2, roots)

    def test_gate_rejects_incomplete_union_and_stale_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = self.make_evidence(tmp)
            with self.assertRaises(ValueError):
                ci_matrix.gate({**self.plan, "head": "b" * 40}, 2, roots)
            for root in roots:
                path = root / "browser-regressions-full.json"
                value = json.loads(path.read_text(encoding="utf-8"))
                value["suites"].append(copy.deepcopy(value["suites"][0]))
                value["suites"][-1]["specs"][0]["title"] = "omitted"
                path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                ci_matrix.gate(self.plan, 2, roots)


if __name__ == "__main__":
    unittest.main()
