"""Analytic sanity checks of analysis helpers only; no worker/evaluator calls."""

import unittest

from report_repeats import bootstrap, numerator_denominator, rate_record


def observation(task, passed, visible=0, fresh=True):
    return {
        "suite": "repobench",
        "split": "train",
        "task_id": task,
        "result": {"evaluation": "passed" if passed else "failed"},
        "visible": {"exit_code": visible},
        "visible_fresh": fresh,
    }


class StatisticsChecks(unittest.TestCase):
    def test_task_clusters_preserve_perfect_within_task_dependence(self):
        # Six attempts but only two independent task outcomes. Drawing whole
        # clusters yields support at 0, 1/2, 1 and interval endpoints 0 and 1.
        runs = [observation("a", True)] * 3 + [observation("b", False)] * 3
        result = rate_record(runs, "success")
        self.assertEqual((result["numerator"], result["denominator"]), (3, 6))
        self.assertEqual(result["bootstrap"]["tasks"], 2)
        self.assertEqual(result["bootstrap"]["lower"], "0")
        self.assertEqual(result["bootstrap"]["upper"], "1")

    def test_false_pass_requires_post_edit_visible_success(self):
        self.assertEqual(
            numerator_denominator(observation("a", False, fresh=False), "false_given_visible_pass"),
            (0, 0),
        )
        self.assertEqual(
            numerator_denominator(observation("a", False, visible=1), "false_given_visible_pass"),
            (0, 0),
        )
        self.assertEqual(
            numerator_denominator(observation("a", False), "false_given_visible_pass"), (1, 1)
        )
        self.assertEqual(
            numerator_denominator(observation("a", True), "false_given_visible_pass"), (0, 1)
        )

    def test_one_cluster_is_not_reported_as_precise(self):
        result = bootstrap([observation("a", True)] * 3, "success")
        self.assertTrue(result["interval"].startswith("not available"))

    def test_bootstrap_is_deterministic(self):
        runs = [observation("a", True), observation("b", False), observation("c", True)]
        self.assertEqual(bootstrap(runs, "success"), bootstrap(runs, "success"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
