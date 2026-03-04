"""
Django Admin — PayMe Payment Actions

FIXED: Added a "Confirm PayMe Payment" button directly on the Order DETAIL page
so admin doesn't have to go back to the list view to confirm a payment.

The action still works from the list view too (select checkbox → Actions → Go).
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.conf import settings
from django.shortcuts import redirect
from django.urls import path
from django.contrib import messages
import logging

logger = logging.getLogger(__name__)

# ── Safe import ───────────────────────────────────────────────────────────────
try:
    from utils.email import send_order_confirmation_email
    logger.info("✅ utils.email imported successfully in admin.py")
except ImportError as e:
    logger.critical(f"❌ FAILED to import send_order_confirmation_email: {e}")
    def send_order_confirmation_email(order):
        raise RuntimeError(f"utils.email import failed at startup: {e}")

from .models import Order, OrderItem


# ─────────────────────────────────────────────────────────────────────────────
# Helper: core confirmation logic (shared by action + detail button)
# ─────────────────────────────────────────────────────────────────────────────

def _do_confirm_payme(order, request=None):
    """
    Confirm a single PayMe order. Returns (success: bool, message: str).
    Optionally adds Django messages if `request` is provided.
    """
    if order.payment_method != 'payme':
        msg = f"Order #{order.order_number} is not a PayMe order."
        logger.warning(msg)
        return False, msg

    if order.payment_status == 'paid':
        msg = f"Order #{order.order_number} is already confirmed."
        logger.info(msg)
        return True, msg

    try:
        order.mark_as_paid()
        order.confirm_order()
        logger.info(f"✅ Order {order.order_number} marked as paid + confirmed")
    except Exception as e:
        msg = f"Failed to mark #{order.order_number} as paid: {e}"
        logger.error(msg, exc_info=True)
        return False, msg

    try:
        send_order_confirmation_email(order)
        logger.info(f"📧 Confirmation email sent for {order.order_number}")
    except Exception as e:
        msg = f"Order #{order.order_number} confirmed, but email failed: {e}"
        logger.error(msg, exc_info=True)
        if request:
            messages.warning(request, f"⚠️ {msg}")
        return True, msg  # Still a success — order IS confirmed

    return True, f"Order #{order.order_number} confirmed and email sent."


# ─────────────────────────────────────────────────────────────────────────────
# List-view Action (checkbox + dropdown)
# ─────────────────────────────────────────────────────────────────────────────

def confirm_payme_payment(modeladmin, request, queryset):
    logger.info(
        f"🔔 confirm_payme_payment ACTION TRIGGERED — "
        f"user={request.user}, count={queryset.count()}, "
        f"ids={list(queryset.values_list('id', flat=True))}"
    )
    confirmed = 0
    skipped = 0

    for order in queryset:
        logger.info(f"  → {order.order_number} | method={order.payment_method} | status={order.payment_status}")
        success, msg = _do_confirm_payme(order, request)
        if success:
            confirmed += 1
        else:
            skipped += 1
            modeladmin.message_user(request, f"⚠️ {msg}", level='warning')

    if confirmed:
        modeladmin.message_user(request, f"✅ Confirmed {confirmed} PayMe order(s).")

confirm_payme_payment.short_description = "✅ Confirm PayMe Payment (mark as paid + send email)"


# ─────────────────────────────────────────────────────────────────────────────
# Inline
# ─────────────────────────────────────────────────────────────────────────────

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product', 'product_name', 'product_price', 'quantity', 'line_total']
    can_delete = False


# ─────────────────────────────────────────────────────────────────────────────
# Order Admin
# ─────────────────────────────────────────────────────────────────────────────

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
        'confirm_payme_button',       # ← button shown on detail page
    ]
    inlines = [OrderItemInline]
    actions = [confirm_payme_payment]
    ordering = ['-created_at']

    fieldsets = (
        ('Order', {
            'fields': ('order_number', 'status', 'language', 'created_at', 'updated_at')
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
                'confirm_payme_button',        # ← sits right under payment_status
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

    # ── Custom URL for the detail-page confirm button ─────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:order_id>/confirm-payme/',
                self.admin_site.admin_view(self.confirm_payme_view),
                name='orders_order_confirm_payme',
            ),
        ]
        return custom + urls

    def confirm_payme_view(self, request, order_id):
        """
        Handles the click from the "Confirm PayMe Payment" button on the detail page.
        Redirects back to the same order detail page afterwards.
        """
        logger.info(f"🔔 confirm_payme_view called — order_id={order_id}, user={request.user}")
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            messages.error(request, f"Order {order_id} not found.")
            return redirect('admin:orders_order_changelist')

        success, msg = _do_confirm_payme(order, request)
        if success:
            messages.success(request, f"✅ {msg}")
        else:
            messages.error(request, f"❌ {msg}")

        return redirect('admin:orders_order_change', order_id)

    # ── "Confirm PayMe Payment" button shown on the detail page ──────────────

    def confirm_payme_button(self, obj):
        """
        Renders a green confirm button on the Order detail page.
        Only shown for pending PayMe orders.
        """
        if not obj or not obj.pk:
            return '—'

        if obj.payment_method != 'payme':
            return '—'

        if obj.payment_status == 'paid':
            return format_html(
                '<span style="color:#16a34a;font-weight:bold">✅ Already Confirmed</span>'
            )

        confirm_url = f'/admin/orders/order/{obj.pk}/confirm-payme/'
        return format_html(
            '''
            <a href="{url}"
               style="
                 display:inline-block;
                 padding:8px 16px;
                 background:#16a34a;
                 color:#fff;
                 border-radius:6px;
                 font-weight:bold;
                 font-size:13px;
                 text-decoration:none;
               "
               onclick="return confirm('Confirm PayMe payment for this order and send confirmation email to customer?')">
              ✅ Confirm PayMe Payment
            </a>
            ''',
            url=confirm_url,
        )
    confirm_payme_button.short_description = 'Confirm Payment'

    # ── get_actions debug log (remove once working) ───────────────────────────

    def get_actions(self, request):
        actions = super().get_actions(request)
        logger.info(f"📋 Actions for {request.user}: {list(actions.keys())}")
        return actions

    # ── Display helpers ───────────────────────────────────────────────────────

    def payment_method_badge(self, obj):
        colours = {
            'payme':      ('#E60028', '📱 PayMe'),
            'card_pay':   ('#1a1a1a', '💳 Card'),
            'apple_pay':  ('#000000', '🍎 Apple Pay'),
            'google_pay': ('#4285F4', '🇬 Google Pay'),
            'alipay':     ('#1677FF', '🟡 AliPay'),
            'wechat_pay': ('#07C160', '💚 WeChat Pay'),
        }
        colour, label = colours.get(obj.payment_method, ('#666', obj.payment_method))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:12px">{}</span>',
            colour, label,
        )
    payment_method_badge.short_description = 'Method'

    def payment_status_badge(self, obj):
        colours = {
            'paid':     '#16a34a',
            'pending':  '#d97706',
            'failed':   '#dc2626',
            'refunded': '#6b7280',
        }
        colour = colours.get(obj.payment_status, '#666')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:12px">{}</span>',
            colour, obj.payment_status.upper(),
        )
    payment_status_badge.short_description = 'Payment'

    def total_display(self, obj):
        return f'HK${obj.total}'
    total_display.short_description = 'Total'

    def payme_link_display(self, obj):
        if obj.payment_method != 'payme' or obj.payment_status == 'paid':
            return '—'

        import urllib.parse

        amount_dollars = float(obj.total)
        payme_phone = getattr(settings, 'PAYME_PHONE_NUMBER', '')
        phone_digits = payme_phone.lstrip('+').replace(' ', '') if payme_phone else ''

        if phone_digits:
            link = (
                f"https://payme.hsbc/payment"
                f"?username={phone_digits}"
                f"&amount={amount_dollars:.2f}"
            )
        else:
            link = f"https://payme.hsbc/payment?amount={amount_dollars:.2f}"

        return format_html(
            '<a href="{}" target="_blank" style="color:#E60028;font-weight:bold">'
            '📱 Open PayMe Link</a>',
            link,
        )
    payme_link_display.short_description = 'PayMe Link'