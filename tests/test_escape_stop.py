import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import control


class EscapeStopTests(unittest.TestCase):
    def test_escape_latches_after_release(self):
        pressed = threading.Event()
        notified = threading.Event()
        stop = control.EscapeStop(pressed.is_set, notified.set)
        stop.start()
        try:
            pressed.set()
            self.assertTrue(notified.wait(2))
            pressed.clear()
            self.assertTrue(stop())
            with self.assertRaises(InterruptedError):
                stop.check()
        finally:
            stop.close()

    def test_no_action_after_escape_during_model_reply(self):
        pressed = threading.Event()
        notified = threading.Event()
        actions = []
        stop = control.EscapeStop(pressed.is_set, notified.set)
        def llm(*args, **kwargs):
            pressed.set()
            self.assertTrue(notified.wait(2))
            return '{"action":"click","x":1,"y":1}'
        with patch.object(control, 'EscapeStop', return_value=stop), patch.object(control, 'log'):
            result = control.computer_task('test', llm, lambda: None,
                shoot=lambda: ('image', (10, 10)),
                act=lambda *args: actions.append(args))
        self.assertIn('stopped', result)
        self.assertEqual(actions, [])


if __name__ == '__main__':
    unittest.main()
