import logging
import threading
import time
import unittest

from backend.search_similar_runtime import (
    SearchExecutionTimeoutError,
    log_search_similar_no_match,
    run_with_timeout,
)


class SearchSimilarRuntimeTestCase(unittest.TestCase):
    def test_run_with_timeout_returns_result_before_deadline(self):
        result = run_with_timeout(lambda: "ok", timeout_seconds=0.2)

        self.assertEqual(result, "ok")

    def test_run_with_timeout_raises_timeout_error(self):
        def _slow_job():
            time.sleep(0.1)
            return "late"

        started_at = time.perf_counter()

        with self.assertRaises(SearchExecutionTimeoutError):
            run_with_timeout(_slow_job, timeout_seconds=0.01)

        self.assertLess(time.perf_counter() - started_at, 0.08)

    def test_run_with_timeout_sets_cancel_event_when_it_times_out(self):
        cancel_event = threading.Event()

        def slow_task():
            time.sleep(0.05)
            return "done"

        with self.assertRaises(SearchExecutionTimeoutError):
            run_with_timeout(slow_task, 0.01, cancel_event=cancel_event)

        self.assertTrue(cancel_event.is_set())

    def test_log_search_similar_no_match_logs_info(self):
        logger = logging.getLogger("backend.search_similar_runtime.test.no_match")

        with self.assertLogs(logger.name, level="INFO") as captured:
            log_search_similar_no_match(
                logger,
                total_elapsed=6.2,
                filter_stage_elapsed=0.0,
                retrieval_elapsed=6.1,
                has_global_filter_images=False,
                has_user_website_filter_images=False,
                result_count=0,
                threshold=0.6,
                user_id=12,
                user_shops=["shop-a"],
            )

        self.assertTrue(
            any("未找到相似度超过阈值的商品" in message for message in captured.output),
        )

    def test_log_search_similar_timeout_logs_warning(self):
        logger = logging.getLogger("backend.search_similar_runtime.test.timeout")

        with self.assertLogs(logger.name, level="WARNING") as captured:
            log_search_similar_no_match(
                logger,
                total_elapsed=31.2,
                filter_stage_elapsed=0.0,
                retrieval_elapsed=31.1,
                has_global_filter_images=True,
                has_user_website_filter_images=True,
                result_count=0,
                threshold=0.45,
                user_id=None,
                user_shops=None,
                timed_out=True,
                timeout_seconds=30.0,
            )

        self.assertTrue(
            any("search_similar 请求超时" in message for message in captured.output),
        )


if __name__ == "__main__":
    unittest.main()
