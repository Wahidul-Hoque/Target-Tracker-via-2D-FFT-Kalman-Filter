import json
import logging
import math
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .runtime import workspace

logger = logging.getLogger(__name__)

TARGET_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}
MAX_TARGET_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TARGET_IMAGE_PIXELS = 32_000_000


def session_key(request):
    if 'workspace' not in request.session:
        request.session['workspace'] = uuid.uuid4().hex
    return request.session['workspace']


def valid_bbox(box):
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(
            isinstance(v, (int, float)) and math.isfinite(v)
            for v in box
        )
    )


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
        data = (
            json.loads(request.body or '{}')
            if request.content_type == 'application/json'
            else {}
        )
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
                    raise ValueError(
                        'Could not decode this video. Try a valid H.264 MP4 file.'
                    ) from exc

            # -------------------------------------------------
            # REFERENCE IMAGE: upload full photo at native size.
            # -------------------------------------------------
            elif action == 'target-upload':
                upload = request.FILES.get('target_image')
                if not upload:
                    raise ValueError('Choose a target image first.')

                suffix = Path(upload.name).suffix.lower()
                if suffix not in TARGET_IMAGE_EXTENSIONS:
                    raise ValueError('Use PNG, JPG, JPEG, BMP or WebP for the target image.')
                if upload.size > MAX_TARGET_IMAGE_BYTES:
                    raise ValueError('Please choose a target image smaller than 20 MB.')

                try:
                    upload.seek(0)
                    with Image.open(upload) as original:
                        image = ImageOps.exif_transpose(original).convert('RGB')
                        width, height = image.size
                        if width * height > MAX_TARGET_IMAGE_PIXELS:
                            raise ValueError('Target image is too large. Use at most 32 megapixels.')
                        if min(width, height) < 8:
                            raise ValueError('Target image is too small.')
                        pixels = np.asarray(image, dtype=np.uint8).copy()
                except ValueError:
                    raise
                except (UnidentifiedImageError, OSError) as exc:
                    raise ValueError('Could not decode this target image.') from exc

                # A new photo invalidates the previous reference ROI until the
                # user explicitly selects a new target region on this image.
                w.reference_image = pixels
                w.reference_name = upload.name
                w.engine.reference_target = None
                w.engine.tracker = type(w.engine.tracker)()
                w.engine.result = None
                w.new_log()

            # -------------------------------------------------
            # REFERENCE IMAGE: remove uploaded image and selected target.
            # Keep the currently opened video/frame available so the user
            # can immediately switch back to manual video target selection.
            # -------------------------------------------------
            elif action == 'target-clear':
                w.reference_image = None
                w.reference_name = ''
                w.engine.reference_target = None
                w.engine.tracker = type(w.engine.tracker)()
                w.engine.result = None
                w.diagnostics = {}
                w.diagnostic_frame = None
                w.new_log()

            # -------------------------------------------------
            # REFERENCE IMAGE: select exact native-pixel ROI.
            # No resizing/enlargement is performed.
            # -------------------------------------------------
            elif action == 'target-select':
                if w.reference_image is None:
                    raise ValueError('Open a target image first.')

                box = data.get('bbox')
                if not valid_bbox(box):
                    raise ValueError('Select a valid target rectangle on the image.')

                x, y, width, height = (int(round(v)) for v in box)
                image_h, image_w = w.reference_image.shape[:2]

                if (
                    min(width, height) < 8
                    or x < 0
                    or y < 0
                    or x + width > image_w
                    or y + height > image_h
                ):
                    raise ValueError(
                        'Select a target at least 8 × 8 pixels, entirely inside the image.'
                    )

                # Exact crop from the original decoded image. No resize.
                crop = w.reference_image[
                    y:y + height,
                    x:x + width,
                ].copy()

                w.engine.select_template(crop)
                w.new_log()

            elif action == 'close':
                # "Close source" closes only the video. Preserve an already
                # selected reference-image target so it can be reused with the
                # next video.
                reference_target = (
                    w.engine.reference_target.copy()
                    if w.engine.reference_target is not None
                    else None
                )

                w.engine.close()
                w.engine = type(w.engine)()
                if reference_target is not None:
                    w.engine.select_template(reference_target)

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
                    if not valid_bbox(box):
                        raise ValueError('Select a valid target rectangle.')
                    w.engine.select(box)
                    w.new_log()

                elif action == 'step':
                    if not w.ended:
                        import time
                        now = time.monotonic()
                        diagnostics = (
                            bool(data.get('diagnostics'))
                            and now - w.last_diagnostic >= .2
                        )
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

            return JsonResponse(
                w.payload(),
                json_dumps_params={'allow_nan': False},
            )

    except (ValueError, TypeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Workspace operation failed')
        return JsonResponse(
            {
                'error': (
                    'Processing failed. Restart the source; '
                    'see the terminal for details.'
                )
            },
            status=500,
        )


@require_GET
@never_cache
def export(request):
    with workspace(session_key(request)) as w:
        if not w.log.total:
            return HttpResponse(
                'Track a target before exporting.',
                status=400,
                content_type='text/plain',
            )

        path = Path(w.directory.name) / 'session.csv'
        try:
            w.log.export(path)
            response = HttpResponse(
                path.read_bytes(),
                content_type='text/csv; charset=utf-8',
            )
        finally:
            path.unlink(missing_ok=True)

        response['Content-Disposition'] = (
            'attachment; filename="signal13_session.csv"'
        )
        return response
