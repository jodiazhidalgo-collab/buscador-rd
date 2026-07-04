import importlib.util
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
PROJECT_ROOT = APP_DIR.parent
UNIFIED_ROOT = PROJECT_ROOT.parents[1]
TEST_DATA_DIR = UNIFIED_ROOT / "_codex_runtime" / "test-data" / "test_job_cancel"
TEST_DATA_DIR = TEST_DATA_DIR.with_name(f"{TEST_DATA_DIR.name}_{os.getpid()}")
os.environ["DATA_DIR"] = str(TEST_DATA_DIR)

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import api.btdigg_rd.jobs as jobmod  # noqa: E402

spec = importlib.util.spec_from_file_location("btdigg_app_module", APP_DIR / "app.py")
app_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(app_module)
create_app = app_module.create_app


class JobCancelTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
        TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = create_app().test_client()
        self._clear_jobs()

    def tearDown(self):
        self._clear_jobs()
        shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)

    def _clear_jobs(self):
        with jobmod.lock:
            for runtime in jobmod.job_runtimes.values():
                process = runtime.process
                if process and process.poll() is None:
                    try:
                        process.terminate()
                    except Exception:
                        pass
            jobmod.jobs.clear()
            jobmod.job_runtimes.clear()

    def _make_job(self, job_id="job_cancel_test", status="queued"):
        runtime = jobmod.create_job_runtime(job_id, jobmod.SEARCH_SCOPE)
        with jobmod.lock:
            jobmod.job_runtimes[job_id] = runtime
            jobmod.jobs[job_id] = {
                "id": job_id,
                "kind": "job",
                "module": "btdigg",
                "action": "search",
                "status": status,
                "payload": {"query": "2160p"},
                "log": [],
                "results": [],
                "cancel_requested": False,
            }
        return runtime

    def test_running_job_blocks_while_cancelling(self):
        self._make_job(status="cancelling")

        current = jobmod.running_job()

        self.assertIsNotNone(current)
        self.assertEqual(current["status"], "cancelling")

    def test_cancel_endpoint_is_idempotent(self):
        job_id = "job_cancel_route"
        self._make_job(job_id=job_id, status="running")

        first = self.client.post(f"/api/job/{job_id}/cancel")
        second = self.client.post(f"/api/job/{job_id}/cancel")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.get_json()["status"], "cancelling")
        self.assertEqual(second.get_json()["status"], "cancelling")

    def test_cancel_before_process_does_not_start_subprocess(self):
        job_id = "job_cancel_before"
        self._make_job(job_id=job_id, status="queued")
        jobmod.cancel_job(job_id)

        with patch.object(jobmod.subprocess, "Popen", side_effect=AssertionError("Popen should not start")):
            jobmod.run_process(job_id, [sys.executable, "-c", "print('no')"], jobmod.BTDIGG_CODE_DIR)

        with jobmod.lock:
            job = dict(jobmod.jobs[job_id])
        self.assertEqual(job["status"], "cancelled")
        self.assertIsNone(job.get("exit_code"))

    def test_cancelled_running_process_does_not_promote_artifacts(self):
        job_id = "job_cancel_running"
        self._make_job(job_id=job_id, status="queued")

        class FakeStdout:
            def __iter__(self):
                return iter([])

        class FakeProcess:
            pid = 12345
            stdout = FakeStdout()

            def __init__(self):
                self.returncode = None
                self.poll_count = 0

            def poll(self):
                self.poll_count += 1
                if self.poll_count == 1:
                    jobmod.cancel_job(job_id)
                    return None
                self.returncode = 130
                return self.returncode

        fake_process = FakeProcess()
        with patch.object(jobmod.subprocess, "Popen", return_value=fake_process):
            with patch.object(jobmod, "_promote_successful_artifacts") as promote:
                jobmod.run_process(job_id, [sys.executable, "-c", "print('x')"], jobmod.BTDIGG_CODE_DIR)

        with jobmod.lock:
            job = dict(jobmod.jobs[job_id])
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["exit_code"], 130)
        promote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
