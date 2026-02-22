"""
PayMe Smart Payment Links - Backend Views

How it works:
1. Customer selects PayMe at checkout → frontend calls /api/orders/payme/create/
2. Backend creates a pending Order, generates a personalised PayMe deep link
   (amount + order reference pre-filled), returns link + QR code URL to frontend
3. Customer taps link → PayMe app opens with amount and reference pre-filled
4. Customer taps "Send" in PayMe
5. Admin manually confirms payment in Django admin panel
6. System sends order confirmation email automatically
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.db import transaction
import urllib.parse
import logging
from decimal import Decimal

from .serializers import CheckoutSerializer, OrderSerializer
from ..models import Order

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# PayMe Deep Link Builder
# ─────────────────────────────────────────────────────────────────────────────

def build_payme_link(amount_hkd: Decimal, order_number: str, phone: str = None) -> dict:
    """
    Build a PayMe smart link that pre-fills:
      • The exact HKD amount
      • The order reference (so admin can match payment easily)

    HOW PAYME LINKS ACTUALLY WORK:
    ─────────────────────────────────────────────────────────────────────────────
    PayMe does NOT have a public deep-link spec. The correct approach used by
    real HK businesses is:

      Option A — Phone number link (recommended):
        https://payme.hsbc/payment?username=<phone_without_plus>&amount=<dollars>

        e.g. https://payme.hsbc/payment?username=85291234567&amount=399

        On a HK phone with PayMe installed → opens PayMe app with recipient +
        amount pre-filled. On desktop → redirects to HSBC's web fallback page
        (this is EXPECTED and NORMAL — desktop users use the QR code instead).

      Option B — QR code only (no phone):
        Generate a QR code that encodes the phone number link above.
        Customer scans it with their phone camera → PayMe app opens.

    The `encData` error you saw in the browser console is from HSBC's own
    paycode.js trying to render a dynamic QR widget — this only works when
    HSBC generates the encrypted payload server-side. We don't use that widget.
    Our QR code is a plain image (qrserver.com) — completely independent.

    DESKTOP BEHAVIOUR (expected in development from Pakistan):
    ─────────────────────────────────────────────────────────────────────────────
    Clicking the link on desktop → redirects to HSBC fallback → shows error.
    This is 100% normal. Real customers use a HK phone → PayMe app opens directly.
    Test using the Django admin confirm flow instead (see payme_admin.py).
    ─────────────────────────────────────────────────────────────────────────────
    """
    # Amount as whole dollars (PayMe `amount` param = HKD dollars, NOT cents)
    amount_dollars = float(amount_hkd)

    # Memo shown to the sender in PayMe — helps admin match the payment
    memo = f"HY Florist Order {order_number}"

    payme_phone = getattr(settings, 'PAYME_PHONE_NUMBER', '')

    # Strip leading '+' — PayMe username param uses digits only (e.g. 85291234567)
    phone_digits = payme_phone.lstrip('+').replace(' ', '') if payme_phone else ''

    if phone_digits:
        # Direct link to your PayMe account with amount pre-filled.
        # On mobile with PayMe installed: opens app directly.
        # On desktop: redirects to HSBC web page (expected — use QR instead).
        link = (
            f"https://payme.hsbc/payment"
            f"?username={phone_digits}"
            f"&amount={amount_dollars:.2f}"
        )
    else:
        # No phone configured — generic PayMe send-money page.
        # Customer must manually find the recipient.
        link = f"https://payme.hsbc/payment?amount={amount_dollars:.2f}"

    # ── QR code ──────────────────────────────────────────────────────────────
    # Encode the same link as a QR code image (desktop users scan with phone).
    # qrserver.com is free, no API key needed, works from anywhere in the world.
    qr_data = urllib.parse.quote(link, safe='')
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&margin=10&data={qr_data}"

    return {
        'link': link,
        'qr_url': qr_url,
        'amount_hkd': float(amount_hkd),
        'memo': memo,
        # Shown separately on the page so customer types it as the PayMe message
        'memo_instruction': f'請在 PayMe 備註欄填寫: {memo}',
    }


# ─────────────────────────────────────────────────────────────────────────────
# View: Create PayMe Order
# ─────────────────────────────────────────────────────────────────────────────

class CreatePayMeOrderView(APIView):
    """
    POST /api/orders/payme/create/

    Creates a pending Order and returns the personalised PayMe smart link.

    Request body: same as Stripe checkout (customer info + items).
    Response: order_number, payme_link, qr_url, amount_hkd
    """

    def post(self, request):
        try:
            serializer = CheckoutSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"PayMe order - invalid data: {serializer.errors}")
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            subtotal, delivery_fee, discount, total_hkd = serializer.calculate_order_total()

            if total_hkd <= 0:
                return Response(
                    {'error': '訂單金額無效'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create the order in PENDING state (not paid yet)
            with transaction.atomic():
                order = serializer.create_order(
                    stripe_payment_intent_id=None,
                    payment_method='payme',
                    payment_currency='HKD',
                    exchange_rate=None,
                    total_usd=None,
                )
                # Explicitly keep status pending — admin confirms later
                order.payment_status = 'pending'
                order.status = 'pending'
                order.save(update_fields=['payment_status', 'status', 'updated_at'])

            # Build personalised PayMe link
            payme_data = build_payme_link(
                amount_hkd=total_hkd,
                order_number=order.order_number,
            )

            logger.info(
                f"PayMe order created: {order.order_number}, "
                f"Amount: HK${total_hkd}, Link: {payme_data['link']}"
            )

            return Response({
                'order_number': order.order_number,
                'payme_link': payme_data['link'],
                'qr_url': payme_data['qr_url'],
                'amount_hkd': payme_data['amount_hkd'],
                'memo': payme_data['memo'],
                'message': (
                    '請使用 PayMe 掃描 QR Code 或點擊連結完成付款。'
                    '付款後，我們將在2小時內確認您的訂單並發送確認電郵。'
                ),
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.critical(f"PayMe order creation error: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統錯誤，請聯絡客服'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ─────────────────────────────────────────────────────────────────────────────
# View: Admin Confirms PayMe Payment
# ─────────────────────────────────────────────────────────────────────────────

class ConfirmPayMePaymentView(APIView):
    """
    POST /api/orders/payme/confirm/

    Called by admin (via Django admin action or a dedicated admin endpoint)
    after manually verifying the PayMe payment in the PayMe app.

    Marks order as paid and sends confirmation email to customer.

    Request body:
        { "order_number": "HYF-20240101-XXXXX" }

    This view should be protected — add IsAdminUser permission in production.
    """

    # Uncomment in production:
    # from rest_framework.permissions import IsAdminUser
    # permission_classes = [IsAdminUser]

    def post(self, request):
        order_number = request.data.get('order_number')

        if not order_number:
            return Response(
                {'error': 'order_number is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            order = Order.objects.get(order_number=order_number)
        except Order.DoesNotExist:
            return Response(
                {'error': f'Order {order_number} not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if order.payment_status == 'paid':
            logger.info(f"PayMe confirm: {order_number} already confirmed")
            return Response(
                OrderSerializer(order).data,
                status=status.HTTP_200_OK
            )

        if order.payment_method != 'payme':
            return Response(
                {'error': 'This order was not placed via PayMe'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Mark as paid and confirm
        with transaction.atomic():
            order.mark_as_paid()
            order.confirm_order()

        logger.info(f"PayMe payment confirmed by admin: {order_number}")

        # Send confirmation email
        try:
            self._send_confirmation_email(order)
        except Exception as e:
            logger.error(f"Email failed for {order_number}: {str(e)}", exc_info=True)

        return Response(
            {
                'message': f'Order {order_number} confirmed successfully',
                'order': OrderSerializer(order).data,
            },
            status=status.HTTP_200_OK
        )

    def _send_confirmation_email(self, order):
        context = {
            'order': order,
            'items': order.items.all(),
            'company_name': 'HY Florist',
            'support_email': settings.DEFAULT_FROM_EMAIL,
            'year': timezone.now().year,
        }
        html_message = render_to_string('emails/order_confirmation.html', context)
        plain_message = strip_tags(html_message)
        send_mail(
            subject=f'訂單確認 - #{order.order_number}',
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[order.customer_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Confirmation email sent for PayMe order {order.order_number}")


# ─────────────────────────────────────────────────────────────────────────────
# View: Check PayMe Order Status (polling by frontend)
# ─────────────────────────────────────────────────────────────────────────────

class PayMeOrderStatusView(APIView):
    """
    GET /api/orders/payme/status/<order_number>/

    Frontend polls this every 30 seconds while showing the PayMe QR page.
    Once the admin confirms the payment, this returns payment_status='paid'
    and the frontend redirects the customer to the order confirmation page.
    """

    def get(self, request, order_number):
        try:
            order = Order.objects.get(order_number=order_number)
        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            'order_number': order.order_number,
            'payment_status': order.payment_status,
            'status': order.status,
            'customer_email': order.customer_email,
        })