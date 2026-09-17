import json
import logging
import math
import uuid
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache
from .runtime import workspace

logger = logging.getLogger(__name__)


def session_key(request):
    if 'workspace' not in request.session:
        request.session['workspace'] = uuid.uuid4().hex
    return request.session['workspace']


@require_GET
@ensure_csrf_cookie
@never_cache
def index(request):
    session_key(request)
    return render(request, 'studio/index.html')


@require_POST
@never_cache
def api(request, action):
    try:
        data = json.loads(request.body or '{}') if request.content_type == 'application/json' else {}
        if not isinstance(data, dict):
            raise ValueError('Expected an object.')
        with workspace(session_key(request)) as w:
            if action == 'state':
                pass
            elif action == 'demo':
                w.load()
            elif action == 'upload':
                upload = request.FILES.get('video')
                if not upload:
                    raise ValueError('Choose a video first.')
                suffix = Path(upload.name).suffix.lower()
                if suffix not in {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v'}:
                    raise ValueError('Use MP4, AVI, MOV, MKV, WebM or M4V.')
                if upload.size > settings.MAX_VIDEO_BYTES:
                    raise ValueError('Please choose a video smaller than 512 MB.')
                path = Path(w.directory.name) / (uuid.uuid4().hex + suffix)
                try:
                    with path.open('wb') as output:
                        for chunk in upload.chunks():
                            output.write(chunk)
                    w.load(str(path), upload.name)
                except Exception as exc:
                    path.unlink(missing_ok=True)
                    raise ValueError('Could not decode this video. Try a valid H.264 MP4 file.') from exc
            elif action == 'close':
                w.engine.close()
                w.engine = type(w.engine)()
                if w.path:
                    Path(w.path).unlink(missing_ok=True)
                w.path, w.name, w.total, w.ended = None, '', None, False
                w.new_log()
            else:
                if w.engine.frame is None:
                    raise ValueError('Load a video or the demo first.')
                if action == 'restart':
                    w.load(w.path, w.name)
                elif action == 'select':
                    box = data.get('bbox')
                    if not isinstance(box, list) or len(box) != 4 or any(
                        not isinstance(v, (int, float)) or not math.isfinite(v) for v in box
                    ):
                        raise ValueError('Select a valid target rectangle.')
                    w.engine.select(box)
                    w.new_log()
                elif action == 'step':
                    if not w.ended:
                        import time
                        now = time.monotonic()
                        diagnostics = bool(data.get('diagnostics')) and now - w.last_diagnostic >= .2
                        result = w.engine.step(diagnostics)
                        if result is None:
                            w.ended = True
                        else:
                            _, r, index = result
                            if r:
                                w.log.append(index, index / w.engine.fps, r)
                                if r.diagnostics:
                                    w.plots(r.diagnostics)
                                    w.last_diagnostic = now
                elif action == 'snapshot':
                    if w.engine.tracker.ready:
                        w.plots(w.engine.snapshot())
                else:
                    raise ValueError('Unknown action.')
            return JsonResponse(w.payload(), json_dumps_params={'allow_nan': False})
    except (ValueError, TypeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Workspace operation failed')
        return JsonResponse({'error': 'Processing failed. Restart the source; see the terminal for details.'}, status=500)


@require_GET
@never_cache
def export(request):
    with workspace(session_key(request)) as w:
        if not w.log.total:
            return HttpResponse('Track a target before exporting.', status=400, content_type='text/plain')
        path = Path(w.directory.name) / 'session.csv'
        try:
            w.log.export(path)
            response = HttpResponse(path.read_bytes(), content_type='text/csv; charset=utf-8')
        finally:
            path.unlink(missing_ok=True)
        response['Content-Disposition'] = 'attachment; filename="signal13_session.csv"'
        return response
