"""
Celery config — stub. Celery is disabled (no Redis broker available).
Re-enable later by restoring proper Celery setup.
"""

# Provide a no-op celery_app so any stray import doesn't crash
class _NoOpTask:
    def apply_async(self, *a, **kw):
        raise RuntimeError("Celery is disabled. Tasks run in background threads instead.")
    def __call__(self, *a, **kw):
        raise RuntimeError("Celery is disabled.")


class _NoOpCelery:
    def task(self, *a, **kw):
        def decorator(fn):
            return fn
        return decorator


celery_app = _NoOpCelery()
