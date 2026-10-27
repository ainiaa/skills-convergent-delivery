"""Author: Jeff.Liu. Output volume must not end a worker's lifetime."""
import errno
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_exec_runner import execute_launch, plan_launch
from test_codex_exec_runner import profile


class RunnerOutputTest(unittest.TestCase):
    def test_invalid_final_message_never_reuses_an_earlier_answer(self):
        from runner_output import OutputLog
        from codex_exec_runner import _response_from_jsonl
        from claude_exec_runner import _response_from_jsonl as claude_response
        for parser, event in (
            (_response_from_jsonl, lambda text: {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}}),
            (claude_response, lambda text: {'type': 'result', 'result': text}),
        ):
            for final in (None, '', 4, '   '):
                with self.subTest(parser=parser.__module__, final=final):
                    log = OutputLog(16, parser)
                    self.addCleanup(shutil.rmtree, log.directory)
                    log.feed('stdout', json.dumps(event('earlier answer')).encode() + b'\n')
                    log.feed('stdout', json.dumps(event(final)).encode() + b'\n')
                    metadata = log.finish()
                    self.assertIsNone(log.response)
                    self.assertIsNone(metadata['result_path'])

    def test_large_real_child_finishes_and_preserves_both_streams_and_final_result(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'finished'
            code = """import json,sys
from pathlib import Path
block=b'x'*65536
for _ in range(640):
 sys.stdout.buffer.write(block+b'\\n')
 sys.stderr.buffer.write(b'e'*8192)
sys.stdout.buffer.write(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'final 中文'}}).encode()+b'\\n')
sys.stdout.flush();sys.stderr.flush()
Path(sys.argv[1]).write_text('finished')
"""
            launch = plan_launch(profile(permissions={'workspace':'read','shell':False,'network':'egress'}, budget={'max_turns':1,'timeout_seconds':20,'max_output_chars':1024}), 'probe', workspace=directory, codex_bin=sys.executable)
            receipt, content = execute_launch(launch, 'probe', allow_execute=True, capture_content=True,
                process_factory=lambda _command, **kwargs: subprocess.Popen([sys.executable,'-c',code,str(marker)], **kwargs))
            self.assertEqual('completed', receipt['status'])
            from runner_contract import runner_results_complete
            self.assertTrue(runner_results_complete([launch], [receipt]))
            self.assertEqual('finished', marker.read_text())
            self.assertEqual('final 中文', content)
            log = receipt['output_log']
            self.addCleanup(shutil.rmtree, log['directory'])
            for name, expected in [('stdout',640*65537),('stderr',640*8192)]:
                parts = sorted(Path(log['directory']).glob(name+'-*.log'))
                self.assertGreater(len(parts), 1)
                self.assertTrue(all(p.stat().st_size <= 1024*1024 for p in parts))
                digest = hashlib.sha256()
                for p in parts:
                    digest.update(p.read_bytes())
                    self.assertEqual(0o600, p.stat().st_mode & 0o777)
                self.assertEqual(receipt[name+'_fingerprint'], digest.hexdigest())
                self.assertGreaterEqual(log['streams'][name]['bytes'], expected)
                self.assertTrue(log['streams'][name]['preview_truncated'])
            self.assertEqual(0o700, Path(log['directory']).stat().st_mode & 0o777)
            self.assertEqual(content, Path(log['result_path']).read_text())

    def test_memory_preview_is_bounded_and_final_record_is_independent(self):
        from runner_output import OutputLog
        from codex_exec_runner import _response_from_jsonl
        log = OutputLog(64, _response_from_jsonl)
        self.addCleanup(shutil.rmtree, log.directory)
        for _ in range(100):
            log.feed('stdout', b'x'*1024)
            log.feed('stderr', b'e'*1024)
        log.feed('stdout', b'\n'+json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'complete result larger than preview budget'*10}}).encode())
        metadata = log.finish()
        self.assertLessEqual(len(log.preview['stdout']), 64)
        self.assertLessEqual(len(log.preview['stderr']), 64)
        self.assertTrue(log.response.startswith('complete result'))
        self.assertEqual(log.response, Path(metadata['result_path']).read_text())

    def test_log_disk_error_does_not_stop_drain_or_hide_missing_evidence(self):
        from runner_output import OutputLog
        from codex_exec_runner import _response_from_jsonl
        log = OutputLog(16, _response_from_jsonl)
        self.addCleanup(shutil.rmtree, log.directory)
        with patch.object(log, '_open_segment', side_effect=OSError(errno.ENOSPC, 'disk full')):
            log.feed('stdout', b'noise\n')
        log.feed('stdout', b'{"type":"item.completed","item":{"type":"agent_message","text":"answer"}}\n')
        metadata = log.finish()
        self.assertEqual('answer', log.response)
        self.assertEqual('partial', metadata['status'])
        self.assertIsNotNone(metadata['error_type'])
        self.assertEqual(0, metadata['streams']['stdout']['written_bytes'])

    def test_large_output_still_obeys_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            launch = plan_launch(profile(permissions={'workspace':'read','shell':False,'network':'egress'}, budget={'max_turns':1,'timeout_seconds':1,'max_output_chars':32}), 'probe', workspace=directory, codex_bin=sys.executable)
            receipt = execute_launch(launch, 'probe', allow_execute=True,
                process_factory=lambda _command, **kwargs: subprocess.Popen([sys.executable,'-c',"import sys,time;sys.stdout.write('x'*100000);sys.stdout.flush();time.sleep(30)"], **kwargs))
            self.assertEqual('timed_out', receipt['status'])
            self.addCleanup(shutil.rmtree, receipt['output_log']['directory'])

    def test_huge_single_log_record_and_split_utf8_do_not_hide_final_result(self):
        from runner_output import OutputLog
        from codex_exec_runner import _response_from_jsonl
        with patch('runner_output.EVENT_BYTES', 128):
            log = OutputLog(8, _response_from_jsonl)
            self.addCleanup(shutil.rmtree, log.directory)
            for _ in range(100): log.feed('stdout', b'x'*32)
            log.feed('stdout', b'\n')
            raw = json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'中文最终结论'}}, ensure_ascii=False).encode()
            for byte in raw: log.feed('stdout', bytes([byte]))
            metadata = log.finish()
        self.assertEqual('中文最终结论', log.response)
        self.assertEqual(1, metadata['skipped_records'])
        self.assertEqual('complete', metadata['status'])

    def test_log_creation_failure_keeps_final_result_and_reports_partial(self):
        from runner_output import OutputLog
        from codex_exec_runner import _response_from_jsonl
        with patch('runner_output.tempfile.mkdtemp', side_effect=PermissionError('no log directory')):
            log = OutputLog(4, _response_from_jsonl)
        log.feed('stdout', b'{"type":"item.completed","item":{"type":"agent_message","text":"answer"}}')
        metadata = log.finish()
        self.assertEqual('answer', log.response)
        self.assertEqual('partial', metadata['status'])
        self.assertIsNone(metadata['directory'])

    def test_user_cancel_reaps_the_started_process(self):
        class Process:
            def __init__(self):
                self.stdin, self.stdout, self.stderr = io.BytesIO(), io.BytesIO(), io.BytesIO()
                self.killed = False
            def wait(self, timeout=None):
                if not self.killed: raise KeyboardInterrupt()
                return -9
            def kill(self): self.killed = True
        process = Process()
        launch = plan_launch(profile(permissions={'workspace':'read','shell':False,'network':'egress'}), 'probe', workspace='/tmp', codex_bin=sys.executable)
        with self.assertRaises(KeyboardInterrupt):
            execute_launch(launch, 'probe', allow_execute=True, process_factory=lambda *_args, **_kwargs:process)
        self.assertTrue(process.killed)

    def test_output_receipts_validate_metadata_and_reject_forged_fields(self):
        import copy
        from runner_output import OutputLog, validate_output_log
        log = OutputLog(4)
        self.addCleanup(shutil.rmtree, log.directory)
        log.feed('stdout', b'large text')
        valid = log.finish()
        validate_output_log(valid)
        for patch_value in [
            {'directory':'relative'}, {'status':'completed'}, {'error_type':'failed'},
            {'status':'partial'}, {'result_path':'/outside/result'}, {'skipped_records':True},
            {'streams':{}}, {'streams':{'stdout':{},'stderr':{}}}, {'extra':True},
        ]:
            bad = copy.deepcopy(valid); bad.update(patch_value)
            with self.assertRaises(ValueError): validate_output_log(bad)
        log.feed('stdout', b'late callback')
        self.assertEqual(10, valid['streams']['stdout']['bytes'])

    def test_oversized_final_record_never_reuses_an_earlier_answer(self):
        from runner_output import OutputLog
        from codex_exec_runner import _response_from_jsonl
        with patch('runner_output.EVENT_BYTES', 128):
            log = OutputLog(8, _response_from_jsonl)
            self.addCleanup(shutil.rmtree, log.directory)
            log.feed('stdout', b'{"type":"item.completed","item":{"type":"agent_message","text":"earlier"}}\n')
            log.feed('stdout', json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'new final '*100}}).encode()+b'\n')
            metadata = log.finish()
        self.assertIsNone(log.response)
        self.assertIsNone(metadata['result_path'])
        self.assertEqual(1, metadata['skipped_records'])

    def test_decoder_resource_error_does_not_stop_later_final_event(self):
        from runner_output import OutputLog
        from codex_exec_runner import _response_from_jsonl
        log = OutputLog(32, _response_from_jsonl)
        self.addCleanup(shutil.rmtree, log.directory)
        log.feed('stdout', b'{"item":{"type":"tool_call","large":'+b'1'*25000+b'}}\n')
        log.feed('stdout', b'{"type":"item.completed","item":{"type":[]}}\n')
        log.feed('stdout', b'{"type":"item.completed","item":{"type":"agent_message","text":"final"}}\n')
        metadata = log.finish()
        self.assertEqual('final', log.response)
        self.assertEqual(2, metadata['skipped_records'])
        self.assertEqual('complete', metadata['status'])

    def test_invalid_unicode_result_is_unavailable_and_never_crashes_finish(self):
        from runner_output import OutputLog
        from codex_exec_runner import _response_from_jsonl
        log = OutputLog(32, _response_from_jsonl)
        self.addCleanup(shutil.rmtree, log.directory)
        log.feed('stdout', json.dumps({'type':'item.completed','item':{'type':'agent_message','text':chr(0xd800)}}).encode()+b'\n')
        metadata = log.finish()
        self.assertIsNone(log.response)
        self.assertIsNone(metadata['result_path'])
        self.assertEqual(1, metadata['skipped_records'])
        self.assertEqual('complete', metadata['status'])

    def test_core_snapshot_can_import_output_receipt_dependency(self):
        from controller_snapshot import create_snapshot
        with tempfile.TemporaryDirectory() as directory:
            snapshot = create_snapshot(Path(__file__).resolve().parents[1], Path(directory)/'controller')
            code = 'import sys;sys.path.insert(0,'+repr(str(Path(snapshot['root'])/'scripts'))+');import runner_contract;from runner_output import validate_output_log'
            result = subprocess.run([sys.executable,'-I','-c',code], cwd=directory, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
