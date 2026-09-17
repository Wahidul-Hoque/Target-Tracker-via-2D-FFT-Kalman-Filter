"""GUI integration checks against the unchanged engine."""
import csv
import io
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, Client, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from signal13.ui.worker import ProcessingEngine
from .runtime import cleanup


@override_settings(ALLOWED_HOSTS=['testserver'])
class WebIntegrationTests(SimpleTestCase):
    def tearDown(self):
        cleanup(True)

    def post(self, action, data=None, client=None):
        response = (client or self.client).post('/api/' + action + '/',
                                               data=json.dumps(data or {}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def test_demo_matches_original_engine_and_exports(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        loaded = self.post('demo')
        self.assertTrue(loaded['ready'])
        direct = ProcessingEngine()
        try:
            direct.load()
            for _ in range(4):
                _, expected, index = direct.step(False)
                actual = self.post('step')
                self.assertEqual(actual['index'], index)
                for key in ('center', 'measurement', 'velocity', 'psr', 'appearance', 'status', 'reason', 'search_box'):
                    value = getattr(expected, key)
                    self.assertEqual(actual['result'][key], list(value) if isinstance(value, tuple) else value)
            snapshot = self.post('snapshot')
            self.assertEqual(snapshot['index'], 4)
            self.assertEqual(len(snapshot['diagnostics']), 4)
            self.assertEqual(snapshot['analytics']['total'], 4)
            exported = self.client.get('/export/')
            self.assertEqual(exported.status_code, 200)
            rows = list(csv.DictReader(io.StringIO(exported.content.decode())))
            self.assertEqual(len(rows), 4)
            self.assertIn('processing_ms', rows[0])
            reset = self.post('restart')
            self.assertEqual(reset['index'], 0)
            self.assertEqual(reset['analytics']['total'], 0)
        finally:
            direct.close()

    def test_roi_validation_session_reset_and_isolation(self):
        self.post('demo')
        self.post('step')
        invalid = self.client.post('/api/select/', data=json.dumps({'bbox': [0, 0, 2, 2]}), content_type='application/json')
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.post('state')['analytics']['total'], 1)
        self.post('restart')
        selected = self.post('select', {'bbox': [70, 125, 40, 40]})
        self.assertTrue(selected['ready'])
        self.assertEqual(selected['analytics']['total'], 0)
        other = Client()
        self.assertFalse(self.post('state', client=other)['loaded'])
        self.assertFalse(self.post('close')['loaded'])
        self.assertEqual(self.client.get('/export/').status_code, 400)

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/demo/').status_code, 403)
        client.get('/')
        response = client.post('/api/demo/', data='{}', content_type='application/json',
                               HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)

    def test_upload_decode_eof_and_corrupt_upload_preserves_source(self):
        import imageio.v2 as imageio
        from signal13.io.sources import DemoSource
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.mp4'
            demo = DemoSource()
            with imageio.get_writer(path, fps=30, macro_block_size=1) as writer:
                for _ in range(4):
                    writer.append_data(demo.next_frame())
            upload = SimpleUploadedFile('sample.mp4', path.read_bytes(), 'video/mp4')
            response = self.client.post('/api/upload/', {'video': upload})
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertFalse(response.json()['ready'])
        self.post('select', {'bbox': [70, 125, 40, 40]})
        for _ in range(4):
            final = self.post('step')
        self.assertTrue(final['ended'])
        self.assertEqual(final['analytics']['total'], 3)
        self.assertEqual(self.post('step')['analytics']['total'], 3)
        corrupt = SimpleUploadedFile('broken.mp4', b'not a video', 'video/mp4')
        self.assertEqual(self.client.post('/api/upload/', {'video': corrupt}).status_code, 400)
        self.assertEqual(self.post('state')['name'], 'sample.mp4')
