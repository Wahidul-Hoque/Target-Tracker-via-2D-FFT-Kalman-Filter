# Django GUI validation

## Passed

- Django system check: no issues.
- Python compilation and JavaScript syntax check.
- Four Django integration tests: all passed.
- Demo results compared against direct calls to the original ProcessingEngine: identical center, measurement, velocity, PSR, appearance, status, reason and search box across tested frames. Processing latency is inherently timing-dependent and was not compared.
- Read-only DSP snapshot preserves frame index and session row count.
- Original CSV field export and row counts verified.
- ROI rejection, target reset, independent browser sessions and CSRF enforcement verified.
- Real MP4 upload/decode, target selection, end-of-video handling and invalid upload recovery verified.
- SHA-256 comparison confirms every original file under signal13/ is unchanged. See GUI_CHANGE_MANIFEST.json.

## Existing core-test failure — deliberately preserved

Running the original test suite against both the untouched upload and the Django project produced the same result: **18 passed, 1 failed**.

`tests/test_core.py::test_demo_and_export` expects maximum demo position error below 1 pixel; the actual maximum was 2.216870450636518 pixels in both copies. The test's occlusion and reacquisition assertions pass before that assertion. Neither the test nor the tracker was changed: fixing tracking behavior is outside this GUI-only task.

## Verification limitation

A live browser visual/interaction check could not be completed in this environment. Browser installation encountered certificate/download failures. No browser screenshots or browser end-to-end pass are claimed. The actual Django API integration tests and source syntax checks above were completed successfully.

## How to reproduce

From the project root in your Python environment:

```bash
python -m pip install -r requirements-dev.txt
python manage.py check
python manage.py test studio -v 2
python -m pytest tests -q
```

Use `python main.py`, then open http://127.0.0.1:8000 to review the interface on your computer.
