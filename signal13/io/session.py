"""Disk-backed full-session CSV with bounded in-memory chart history."""
from collections import deque
import csv
import shutil
import tempfile

FIELDS = ['frame', 'time_s', 'status', 'x', 'y', 'vx', 'vy', 'measurement_x',
          'measurement_y', 'psr', 'appearance', 'misses', 'processing_ms', 'reason']


class SessionLog:
    def __init__(self):
        self.stream = tempfile.TemporaryFile(mode='w+', newline='', encoding='utf-8')
        self.writer = csv.DictWriter(self.stream, fieldnames=FIELDS)
        self.writer.writeheader()
        self.rows = deque(maxlen=600)
        self.total = self.accepted = 0

    def append(self, frame, timestamp, result):
        measurement = result.measurement or ('', '')
        row = dict(zip(FIELDS, [frame, timestamp, result.status, *result.center,
                               *result.velocity, *measurement, result.psr,
                               result.appearance, result.misses, result.processing_ms,
                               getattr(result, 'reason', '')]))  # why rejected, or 'reacquired'
        self.writer.writerow(row)
        self.rows.append(row)
        self.total += 1
        self.accepted += result.measurement is not None

    def export(self, path):
        self.stream.flush()
        self.stream.seek(0)
        try:
            with open(path, 'w', newline='', encoding='utf-8') as output:
                shutil.copyfileobj(self.stream, output)
        finally:
            self.stream.seek(0, 2)

    def close(self):
        self.stream.close()
