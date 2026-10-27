"""Author: Jeff.Liu. Spool runner output without coupling output volume to process lifetime."""
import json
import os
import tempfile
from pathlib import Path

SEGMENT_BYTES = 1024 * 1024
# A single protocol event is decoded separately from execution logs; oversized events remain on disk.
EVENT_BYTES = 8 * 1024 * 1024


class OutputLog:
    def __init__(self, preview_limit, parser=None):
        if type(preview_limit) is not int or preview_limit < 1:
            raise ValueError('output preview budget must be a positive integer')
        self.limit = preview_limit
        self.parser = parser
        self.preview = {name: bytearray() for name in ('stdout', 'stderr')}
        self.streams = {name: {'bytes': 0, 'written_bytes': 0, 'segments': 0,
                               'preview_truncated': False} for name in self.preview}
        self.files = {}
        self.positions = {}
        self.failed = set()
        self.errors = []
        self.response = None
        self.line = bytearray()
        self.discard = False
        self.skipped_records = 0
        self.directory = None
        self.finished = False
        try:
            self.directory = Path(tempfile.mkdtemp(prefix='converge-output-'))
        except OSError as error:
            self.errors.append(f'{type(error).__name__}:{error.errno}' if error.errno is not None else type(error).__name__)

    def _open_segment(self, name):
        count = self.streams[name]['segments']
        path = self.directory / f'{name}-{count:06d}.log'
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self.files[name] = os.fdopen(descriptor, 'wb', buffering=0)
        self.positions[name] = 0
        self.streams[name]['segments'] += 1

    def _close(self, name):
        file = self.files.pop(name, None)
        if file is not None:
            try:
                file.close()
            except OSError as error:
                self.errors.append(f'{type(error).__name__}:{error.errno}' if error.errno is not None else type(error).__name__)

    def _spool(self, name, chunk):
        if self.directory is None or name in self.failed:
            return
        try:
            offset = 0
            while offset < len(chunk):
                if name not in self.files:
                    self._open_segment(name)
                amount = min(SEGMENT_BYTES - self.positions[name], len(chunk) - offset)
                written = self.files[name].write(chunk[offset:offset + amount])
                if not written:
                    raise OSError('output log write made no progress')
                offset += written
                self.positions[name] += written
                self.streams[name]['written_bytes'] += written
                if self.positions[name] == SEGMENT_BYTES:
                    self._close(name)
        except OSError as error:
            self.errors.append(f'{type(error).__name__}:{error.errno}' if error.errno is not None else type(error).__name__)
            self.failed.add(name)
            self._close(name)

    def _record(self):
        raw = bytes(self.line)
        self.line.clear()
        if raw:
            try:
                result = self.parser(raw)
                if isinstance(result, str) and result.strip():
                    result.encode('utf-8')
                    self.response = result
            except (ValueError, TypeError, RecursionError):
                # Decoder resource/Unicode errors concern this record, never the worker's lifetime.
                self.response = None
                self.skipped_records += 1

    def feed(self, name, chunk):
        if self.finished:
            return
        self.streams[name]['bytes'] += len(chunk)
        self.streams[name]['preview_truncated'] = self.streams[name]['bytes'] > self.limit
        if len(chunk) >= self.limit:
            self.preview[name][:] = chunk[-self.limit:]
        else:
            self.preview[name].extend(chunk)
            del self.preview[name][:-self.limit]
        self._spool(name, chunk)
        if name == 'stdout' and self.parser is not None:
            pieces = chunk.split(b'\n')
            for index, piece in enumerate(pieces):
                if not self.discard:
                    if len(self.line) + len(piece) <= EVENT_BYTES:
                        self.line.extend(piece)
                    else:
                        self.line.clear()
                        self.response = None
                        self.discard = True
                        self.skipped_records += 1
                if index < len(pieces) - 1:
                    if not self.discard:
                        self._record()
                    self.discard = False

    def chunks(self, name):
        for index in range(self.streams[name]['segments']):
            with (self.directory / f'{name}-{index:06d}.log').open('rb') as source:
                while chunk := source.read(8192):
                    yield chunk

    def finish(self):
        self.finished = True
        if self.parser is not None and not self.discard:
            self._record()
        for name in list(self.files):
            self._close(name)
        result_path = None
        if self.response is not None:
            try:
                self.response.encode('utf-8')
            except UnicodeError:
                self.response = None
                self.skipped_records += 1
        if self.directory is not None and self.response is not None:
            path = self.directory / 'result.txt'
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as result:
                    result.write(self.response)
                result_path = str(path)
            except (OSError, UnicodeError) as error:
                number = getattr(error, 'errno', None)
                self.errors.append(f'{type(error).__name__}:{number}' if number is not None else type(error).__name__)
        return {'directory': str(self.directory) if self.directory is not None else None,
                'status': 'partial' if self.errors else 'complete',
                'error_type': self.errors[0] if self.errors else None,
                'streams': {name: dict(value) for name, value in self.streams.items()}, 'result_path': result_path,
                'skipped_records': self.skipped_records}


def validate_output_log(value):
    if not isinstance(value, dict) or set(value) != {
        'directory', 'status', 'error_type', 'streams', 'result_path', 'skipped_records'
    }:
        raise ValueError('runner output log fields are invalid')
    directory = value['directory']
    if directory is not None and (not isinstance(directory, str) or not Path(directory).is_absolute()):
        raise ValueError('runner output log directory is invalid')
    if value['status'] not in {'complete', 'partial'} or (
        value['status'] == 'complete' and (directory is None or value['error_type'] is not None)
        or value['status'] == 'partial' and (not isinstance(value['error_type'], str) or not value['error_type'])
    ):
        raise ValueError('runner output log status is invalid')
    if value['result_path'] is not None and (
        directory is None or value['result_path'] != str(Path(directory) / 'result.txt')
    ):
        raise ValueError('runner output log result path is invalid')
    if type(value['skipped_records']) is not int or value['skipped_records'] < 0:
        raise ValueError('runner output log skipped count is invalid')
    streams = value['streams']
    if not isinstance(streams, dict) or set(streams) != {'stdout', 'stderr'}:
        raise ValueError('runner output log streams are invalid')
    for stream in streams.values():
        if not isinstance(stream, dict) or set(stream) != {'bytes', 'written_bytes', 'segments', 'preview_truncated'} \
                or any(type(stream[k]) is not int or stream[k] < 0 for k in ('bytes', 'written_bytes', 'segments')) \
                or stream['written_bytes'] > stream['bytes'] or type(stream['preview_truncated']) is not bool:
            raise ValueError('runner output log stream fields are invalid')
        if value['status'] == 'complete' and stream['written_bytes'] != stream['bytes']:
            raise ValueError('complete runner output log has missing bytes')
