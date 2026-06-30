import importlib.util
import tempfile
import time
import unittest
from pathlib import Path


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"
spec = importlib.util.spec_from_file_location("rd_turbo_pro_cancel_test", MOTOR_FILE)
motor = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(motor)


class MotorCancelTests(unittest.TestCase):
    def test_user_cancelled_is_not_caught_by_exception(self):
        self.assertFalse(issubclass(motor.UserCancelled, Exception))
        self.assertTrue(issubclass(motor.UserCancelled, BaseException))

    def test_cancel_file_triggers_checkpoint(self):
        previous = motor.CANCEL_FILE
        with tempfile.TemporaryDirectory() as tmp:
            cancel_file = Path(tmp) / "cancel.json"
            cancel_file.write_text('{"cancel_requested": true}', encoding="utf-8")
            motor.CANCEL_FILE = cancel_file
            try:
                with self.assertRaises(motor.UserCancelled):
                    motor.cancel_checkpoint("unit")
            finally:
                motor.CANCEL_FILE = previous

    def test_sleep_interruptible_returns_without_cancel(self):
        previous = motor.CANCEL_FILE
        motor.CANCEL_FILE = None
        try:
            started = time.monotonic()
            motor.sleep_interruptible(0.01, step=0.01, where="unit")
            self.assertLess(time.monotonic() - started, 0.2)
        finally:
            motor.CANCEL_FILE = previous


if __name__ == "__main__":
    unittest.main()
