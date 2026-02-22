"""
Django Admin — PayMe Payment Actions

Adds a "✅ Confirm PayMe Payment" button in the Order admin so your team
can mark a PayMe order as paid after checking the PayMe app.

Usage:
  1. Admin opens Django Admin → Orders
  2. Filters by payment_method = 'payme', payment_status = 'pending'
  3. Selects the relevant order(s)
  4. Chooses "Confirm PayMe Payment" from the Actions dropdown
  5. Clicks "Go" → order is marked paid, confirmation email is sent

Add this to your existing orders/admin.py or replace it entirely.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

from utils.email import send_order_confirmation_email
from .models import Order, OrderItem

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Admin Action
# ─────────────────────────────────────────────────────────────────────────────

@admin.action(description="✅ Confirm PayMe Payment (mark as paid + send email)")
def confirm_payme_payment(modeladmin, request, queryset):
    logger.info(f"Action triggered — queryset count: {queryset.count()}")
    """
    Bulk action: mark selected PayMe orders as paid and send confirmation emails.
    Only processes orders that are:
      - payment_method = 'payme'
      - payment_status = 'pending'
    """
    confirmed = 0
    skipped = 0

    for order in queryset:
        logger.info(
            f"Processing order: {order.order_number}, method: {order.payment_method}, status: {order.payment_status}")
        if order.payment_method != 'payme':
            modeladmin.message_user(
                request,
                f"⚠️ Skipped Order #{order.order_number} — not a PayMe order.",
                level='warning'
            )
            skipped += 1
            continue

        if order.payment_status == 'paid':
            modeladmin.message_user(
                request,
                f"ℹ️ Order #{order.order_number} already confirmed.",
                level='info'
            )
            skipped += 1
            continue

        # Mark as paid
        order.mark_as_paid()
        order.confirm_order()
        logger.info(f"Admin confirmed PayMe payment for order {order.order_number}")

        try:
            send_order_confirmation_email(order)
            logger.info(f"Confirmation email sent for {order.order_number}")
        except Exception as e:
            logger.error(f"Email failed for {order.order_number}: {str(e)}", exc_info=True)
            modeladmin.message_user(
                request,
                f"⚠️ Order #{order.order_number} confirmed, but email failed: {str(e)}",
                level='warning'
            )

        confirmed += 1

    if confirmed:
        modeladmin.message_user(
            request,
            f"✅ Successfully confirmed {confirmed} PayMe order(s).",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Order Admin
# ─────────────────────────────────────────────────────────────────────────────

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product', 'product_name', 'product_price', 'quantity', 'line_total']
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_number',
        'customer_name',
        'payment_method_badge',
        'payment_status_badge',
        'total_display',
        'delivery_date',
        'created_at',
    ]
    list_filter = [
        'payment_method',
        'payment_status',
        'status',
        'delivery_date',
        'created_at',
    ]
    search_fields = [
        'order_number',
        'customer_name',
        'customer_email',
        'customer_phone',
    ]
    readonly_fields = [
        'order_number',
        'created_at',
        'updated_at',
        'paid_at',
        'payment_verified_at',
        'confirmed_at',
        'payme_link_display',
    ]
    inlines = [OrderItemInline]
    actions = [confirm_payme_payment]
    ordering = ['-created_at']

    fieldsets = (
        ('Order', {
            'fields': ('order_number', 'status','language', 'created_at', 'updated_at')
        }),
        ('Customer', {
            'fields': ('customer_name', 'customer_email', 'customer_phone')
        }),
        ('Delivery', {
            'fields': ('delivery_address', 'delivery_date', 'delivery_notes')
        }),
        ('Payment', {
            'fields': (
                'payment_method',
                'payment_status',
                'stripe_payment_intent_id',
                'payme_link_display',
                'paid_at',
                'payment_verified_at',
                'confirmed_at',
                'payment_currency',
                'exchange_rate',
                'total_usd',
            )
        }),
        ('Totals', {
            'fields': ('subtotal', 'delivery_fee', 'discount', 'total')
        }),
    )

    def payment_method_badge(self, obj):
        colours = {
            'payme': ('#E60028', '📱 PayMe'),
            'card_pay': ('#1a1a1a', '💳 Card'),
            'apple_pay': ('#000000', '🍎 Apple Pay'),
            'google_pay': ('#4285F4', '🇬 Google Pay'),
            'alipay': ('#1677FF', '🟡 AliPay'),
            'wechat_pay': ('#07C160', '💚 WeChat Pay'),
        }
        colour, label = colours.get(obj.payment_method, ('#666', obj.payment_method))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{}</span>',
            colour, label
        )
    payment_method_badge.short_description = 'Method'

    def payment_status_badge(self, obj):
        colours = {
            'paid': '#16a34a',
            'pending': '#d97706',
            'failed': '#dc2626',
            'refunded': '#6b7280',
        }
        colour = colours.get(obj.payment_status, '#666')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{}</span>',
            colour, obj.payment_status.upper()
        )
    payment_status_badge.short_description = 'Payment'

    def total_display(self, obj):
        return f'HK${obj.total}'
    total_display.short_description = 'Total'

    def payme_link_display(self, obj):
        """Show a clickable PayMe link for pending PayMe orders in the detail view."""
        if obj.payment_method != 'payme' or obj.payment_status == 'paid':
            return '—'

        import urllib.parse
        from decimal import Decimal

        memo = f"HY Florist Order {obj.order_number}"
        amount_cents = int(obj.total * 100)
        payme_phone = getattr(settings, 'PAYME_PHONE_NUMBER', '')
        encoded_memo = urllib.parse.quote(memo)

        if payme_phone:
            link = (
                f"https://payme.hsbc/payment"
                f"?to={urllib.parse.quote(payme_phone)}"
                f"&amount={amount_cents}&currency=HKD&memo={encoded_memo}"
            )
        else:
            link = (
                f"https://payme.hsbc/payment"
                f"?amount={amount_cents}&currency=HKD&memo={encoded_memo}"
            )

        return format_html(
            '<a href="{}" target="_blank" style="color:#E60028;font-weight:bold">📱 Open PayMe Link</a>',
            link
        )
    payme_link_display.short_description = 'PayMe Link'