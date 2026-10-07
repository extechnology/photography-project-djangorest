# Apply cross-version CheckConstraint compatibility early during Django / Celery startup
import inspect
from django.db import models

if not getattr(models.CheckConstraint, '_is_compat_patched', False):
    _orig_check_constraint_init = models.CheckConstraint.__init__
    _check_constraint_params = set(inspect.signature(_orig_check_constraint_init).parameters.keys())
    _accepts_condition = 'condition' in _check_constraint_params
    _accepts_check = 'check' in _check_constraint_params

    def _compat_check_constraint_init(self, *args, **kwargs):
        if _accepts_condition and not _accepts_check:
            if 'check' in kwargs and 'condition' not in kwargs:
                kwargs['condition'] = kwargs.pop('check')
        elif _accepts_check and not _accepts_condition:
            if 'condition' in kwargs and 'check' not in kwargs:
                kwargs['check'] = kwargs.pop('condition')
        return _orig_check_constraint_init(self, *args, **kwargs)

    models.CheckConstraint.__init__ = _compat_check_constraint_init
    models.CheckConstraint._is_compat_patched = True

from .celery import app as celery_app

__all__ = ("celery_app",)