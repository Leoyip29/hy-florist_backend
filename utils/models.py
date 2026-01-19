from django.contrib.auth import get_user_model
from django.db import models


class WithTimeStamps(models.Model):
    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
