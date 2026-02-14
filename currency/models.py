from django.db import models

from utils.models import WithTimeStamps


class CurrencyRate(WithTimeStamps):
    base_currency = models.CharField(max_length=10)
    target_currency = models.CharField(max_length=10)
    rate = models.DecimalField(max_digits=20, decimal_places=10)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.base_currency} -> {self.target_currency} = {self.rate}"
