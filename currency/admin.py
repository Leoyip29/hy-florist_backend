"""
Django Admin Configuration for CurrencyRate Model
Add this to your orders/admin.py file
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import CurrencyRate


@admin.register(CurrencyRate)
class CurrencyRateAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'base_currency',
        'target_currency',
        'rate',
        'created_at',
        'updated_at',
    ]
    date_hierarchy = 'created_at'
    ordering = ['-id']  # Newest first
