"""Mock-only watchdog tests: no subprocesses, installers, signals or GUI launch."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('owned_command', Path(__file__).with_name('run-owned.py'))
owned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned)


class CommandTests(unittest.TestCase):
    def execute(self, wait=0, cleanup_error=None, spawn_error=None):
        events = []
        owner = Mock()
        def cleanup():
            events.append('cleanup')
            if cleanup_error:
                raise cleanup_error
        owner.cleanup.side_effect = cleanup
        child = Mock()
        def finish(timeout):
            events.append('wait')
            if isinstance(wait, BaseException):
                raise wait
            return wait
        child.wait.side_effect = finish
        def factory():
            events.append('containment')
            return owner
        def spawn(*args, **kwargs):
            events.append('spawn')
            if spawn_error:
                raise spawn_error
            return child
        result = owned.run_owned(['mock-only'], 3, factory, popen=spawn,
            ignore_signals=lambda: events.append('ignore'), report=lambda message: None)
        events.append('returned')
        return result, events

    def test_success_waits_for_cleanup_before_return(self):
        result, events = self.execute()
        self.assertEqual(result, 0)
        self.assertEqual(events, ['containment', 'spawn', 'wait', 'ignore', 'cleanup', 'returned'])

    def test_timeout_reaps_before_124(self):
        result, events = self.execute(subprocess.TimeoutExpired('mock-only', 3))
        self.assertEqual(result, 124)
        self.assertLess(events.index('cleanup'), events.index('returned'))

    def test_timeout_cleanup_failure_overrides_124(self):
        result, _ = self.execute(subprocess.TimeoutExpired('mock-only', 3), TimeoutError('stuck'))
        self.assertEqual(result, 125)

    def test_nonzero_exit_still_cleans(self):
        result, events = self.execute(7)
        self.assertEqual(result, 7)
        self.assertIn('cleanup', events)

    def test_launch_error_cleans_and_returns_uncertain(self):
        result, events = self.execute(spawn_error=OSError('mock launch failure'))
        self.assertEqual(result, 125)
        self.assertIn('cleanup', events)

    def test_containment_failure_never_launches(self):
        spawn = Mock()
        self.assertEqual(owned.run_owned(['mock-only'], 3, Mock(side_effect=OSError('job failure')),
            popen=spawn, report=lambda message: None), 125)
        spawn.assert_not_called()

    def test_interruption_cleans_before_return(self):
        result, events = self.execute(InterruptedError())
        self.assertEqual(result, 130)
        self.assertIn('cleanup', events)


@unittest.skipUnless(sys.platform == "linux", "Linux-specific signal adapter")
class LinuxTests(unittest.TestCase):
    def test_arms_cleanup_deadline_and_reaps(self):
        helpers = Mock()
        owner = owned.LinuxOwnership(helpers)
        helpers.linux_subreaper.assert_called_once_with()
        with patch.object(owned.signal, 'signal', return_value='old') as install, \
                patch.object(owned.signal, 'setitimer') as alarm:
            owner.cleanup()
        helpers.reap_linux_descendants.assert_called_once_with()
        self.assertEqual(alarm.call_args_list[0].args, (owned.signal.ITIMER_REAL, 30))
        self.assertEqual(alarm.call_args_list[1].args, (owned.signal.ITIMER_REAL, 0))
        self.assertEqual(install.call_args_list[-1].args, (owned.signal.SIGALRM, 'old'))

    def test_reaper_failure_restores_deadline_handler(self):
        helpers = Mock()
        helpers.reap_linux_descendants.side_effect = TimeoutError('owned task stuck')
        owner = owned.LinuxOwnership(helpers)
        with patch.object(owned.signal, 'signal', return_value='old') as install, \
                patch.object(owned.signal, 'setitimer') as alarm:
            with self.assertRaises(TimeoutError):
                owner.cleanup()
        self.assertEqual(alarm.call_args_list[-1].args, (owned.signal.ITIMER_REAL, 0))
        self.assertEqual(install.call_args_list[-1].args, (owned.signal.SIGALRM, 'old'))


class JobTests(unittest.TestCase):
    def api(self, snapshots, members=None):
        api = Mock()
        api.members.side_effect = snapshots
        api.open_process.side_effect = lambda pid: f'handle-{pid}'
        api.is_member.side_effect = members
        if members is None:
            api.is_member.return_value = True
        api.wait.return_value = True
        return api

    def test_waits_exact_handles_and_reenumerates_new_descendants(self):
        api = self.api([[10, 11], [10, 12], [10]])
        owned.drain_windows_members(api, own_pid=10)
        self.assertEqual([call.args for call in api.terminate.call_args_list], [('handle-11',), ('handle-12',)])
        self.assertEqual([call.args for call in api.wait.call_args_list], [('handle-11', 100), ('handle-12', 100)])
        self.assertEqual(api.close.call_count, 2)
        api.open_process.assert_any_call(11)
        self.assertNotIn(('handle-10',), [call.args for call in api.terminate.call_args_list])

    def test_reused_pid_is_never_terminated_or_waited(self):
        api = self.api([[10, 11], [10]], members=[False])
        owned.drain_windows_members(api, own_pid=10)
        api.terminate.assert_not_called()
        api.wait.assert_not_called()
        api.close.assert_called_once_with('handle-11')

    def test_vanished_member_is_rechecked(self):
        api = self.api([[10, 11], [10]])
        api.open_process.side_effect = lambda pid: None
        owned.drain_windows_members(api, own_pid=10)
        self.assertEqual(api.members.call_count, 2)
        api.terminate.assert_not_called()

    def test_stuck_member_errors_and_closes_handle(self):
        api = self.api([[10, 11]])
        api.wait.return_value = False
        clock = Mock(side_effect=[0, 0, 0, 31])
        with self.assertRaises(TimeoutError):
            owned.drain_windows_members(api, own_pid=10, clock=clock)
        api.close.assert_called_once_with('handle-11')

    def test_missing_self_is_uncertain(self):
        api = self.api([[]])
        with self.assertRaises(RuntimeError):
            owned.drain_windows_members(api, own_pid=10)
        api.terminate.assert_not_called()

    def test_query_failure_propagates(self):
        api = self.api([OSError('query failure')])
        with self.assertRaises(OSError):
            owned.drain_windows_members(api, own_pid=10)

    def test_membership_check_failure_closes_without_terminating(self):
        api = self.api([[10, 11]], members=[OSError('membership failure')])
        with self.assertRaises(OSError):
            owned.drain_windows_members(api, own_pid=10)
        api.close.assert_called_once_with('handle-11')
        api.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
