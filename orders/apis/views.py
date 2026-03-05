from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import HttpResponse
from django.db import transaction, IntegrityError
from django.utils import timezone
import stripe
import logging
from decimal import Decimal

from currency.models import CurrencyRate
from utils.email import send_order_confirmation_email
from .serializers import CheckoutSerializer, OrderSerializer
from ..models import Order, StripeWebhookEvent

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)


class CreatePaymentIntentView(APIView):
    """
    Create a SINGLE Stripe Payment Intent based on selected payment method.

    OPTIMIZED APPROACH - No wasted Payment Intents:
    - User selects payment method FIRST on frontend
    - Backend creates ONLY ONE Payment Intent in appropriate currency
    - Cards/Wallets → HKD Payment Intent
    - AliPay/WeChat Pay → USD Payment Intent

    Request must include:
    - selected_payment_method: 'card' | 'alipay' | 'wechat_pay'
    """

    PAYMENT_METHOD_CURRENCY_MAP = {
        'card': 'hkd',  # Cards, Apple Pay, Google Pay
        'apple_pay': 'hkd',
        'google_pay': 'hkd',
        'alipay': 'usd',  # AliPay & WeChat Pay → USD (Stripe requirement)
        'wechat_pay': 'usd',  # WeChat Pay (same as AliPay, both use USD)
    }

    def post(self, request):
        try:
            # Get selected payment method from request
            selected_method = request.data.get('selected_payment_method', 'card')

            if selected_method not in self.PAYMENT_METHOD_CURRENCY_MAP:
                logger.warning(f"Invalid payment method: {selected_method}")
                return Response(
                    {'error': '無效的付款方式'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate checkout data
            serializer = CheckoutSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"Invalid checkout data: {serializer.errors}")
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Calculate total in HKD (our base currency)
            subtotal, delivery_fee, discount, total_hkd = serializer.calculate_order_total()

            # Validate HKD amount
            if total_hkd <= 0:
                logger.error(f"Invalid order total: {total_hkd} HKD")
                return Response(
                    {'error': '訂單金額無效'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if total_hkd > Decimal('100000.00'):
                logger.warning(f"Order total exceeds limit: {total_hkd} HKD")
                return Response(
                    {'error': '訂單金額超過限制'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Determine currency based on payment method
            payment_currency = self.PAYMENT_METHOD_CURRENCY_MAP[selected_method]

            # Prepare shared metadata
            metadata = {
                'customer_name': serializer.validated_data['customer_name'],
                'customer_email': serializer.validated_data['customer_email'],
                'customer_phone': serializer.validated_data['customer_phone'],
                'integration': 'HY Florist',
                'order_type': 'funeral_flowers',
                'total_hkd': str(total_hkd),
                'payment_currency': payment_currency.upper(),
                'selected_payment_method': selected_method,
                'language': serializer.validated_data.get('language', 'zh-HK'),
            }

            # Create Payment Intent in appropriate currency
            if payment_currency == 'hkd':
                # ============================================================
                # HKD PAYMENT INTENT (Cards, Apple Pay, Google Pay)
                # ============================================================
                amount = int(total_hkd * 100)
                currency = 'hkd'

                payment_intent = stripe.PaymentIntent.create(
                    amount=amount,
                    currency=currency,
                    payment_method_types=['card'],  # Supports cards, Apple Pay, Google Pay
                    metadata=metadata
                )

                logger.info(
                    f"HKD Payment Intent created: {payment_intent.id}, "
                    f"Amount: HK${total_hkd}, Method: {selected_method}"
                )

                response_data = {
                    'clientSecret': payment_intent.client_secret,
                    'paymentIntentId': payment_intent.id,
                    'currency': 'hkd',
                    'amount': float(total_hkd),
                    'displayAmount': f'HK${total_hkd:.2f}',
                    'conversionDetails': {
                        'amountHKD': float(total_hkd),
                        'amountUSD': None,
                        'exchangeRate': None,
                    }
                }

            else:  # USD for AliPay / WeChat Pay
                # ============================================================
                # USD PAYMENT INTENT (AliPay & WeChat Pay)
                # Both payment methods use USD and are enabled together
                # ============================================================
                # Get exchange rate
                currency_rate = CurrencyRate.objects.filter(
                    base_currency='USD',
                    target_currency='HKD'
                ).order_by('-created_at').first()

                if not currency_rate:
                    logger.error("No USD to HKD exchange rate found")
                    return Response(
                        {'error': '暫時無法處理付款,請稍後再試'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                exchange_rate = currency_rate.rate
                total_usd = (total_hkd / exchange_rate).quantize(Decimal('0.01'))

                amount = int(total_usd * 100)
                currency = 'usd'

                # Add USD-specific metadata
                metadata['total_usd'] = str(total_usd)
                metadata['exchange_rate'] = str(exchange_rate)

                # Enable BOTH AliPay and WeChat Pay in the Payment Element
                # User can choose either one when they see Stripe's payment form
                payment_intent = stripe.PaymentIntent.create(
                    amount=amount,
                    currency=currency,
                    payment_method_types=['alipay', 'wechat_pay'],  # Both enabled
                    metadata=metadata
                )

                logger.info(
                    f"USD Payment Intent created: {payment_intent.id}, "
                    f"Amount: US${total_usd} (HK${total_hkd}), "
                    f"Rate: {exchange_rate}, Selected: {selected_method}"
                )

                response_data = {
                    'clientSecret': payment_intent.client_secret,
                    'paymentIntentId': payment_intent.id,
                    'currency': 'usd',
                    'amount': float(total_usd),
                    'displayAmount': f'US${total_usd:.2f}',
                    'conversionDetails': {
                        'amountHKD': float(total_hkd),
                        'amountUSD': float(total_usd),
                        'exchangeRate': float(exchange_rate),
                    }
                }

            return Response(response_data)

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {str(e)}", exc_info=True)
            return Response(
                {'error': '付款系統錯誤,請稍後再試'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        except Exception as e:
            logger.critical(f"Unexpected error: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統錯誤,請聯絡客服'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ConfirmOrderView(APIView):
    """
    Confirm order after successful payment.
    Handles both HKD and USD Payment Intents seamlessly.
    """

    def post(self, request):
        try:
            payment_intent_id = request.data.get('payment_intent_id')

            if not payment_intent_id:
                logger.warning("Order confirmation attempted without payment_intent_id")
                return Response(
                    {'error': 'Payment Intent ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # STEP 1: Verify payment with Stripe
            try:
                payment_intent = stripe.PaymentIntent.retrieve(
                    payment_intent_id,
                    expand=['payment_method']
                )

                if payment_intent.status != 'succeeded':
                    logger.warning(
                        f"Payment Intent {payment_intent_id} status is {payment_intent.status}"
                    )
                    return Response(
                        {'error': '付款尚未完成'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Extract currency and amounts from Payment Intent
                payment_currency = payment_intent.currency.upper()
                paid_amount = Decimal(payment_intent.amount) / 100

                # Get HKD total from metadata
                total_hkd = Decimal(payment_intent.metadata.get('total_hkd', '0'))

                # Get USD details if payment was in USD
                if payment_currency == 'USD':
                    total_usd = Decimal(payment_intent.metadata.get('total_usd', '0'))
                    exchange_rate = Decimal(payment_intent.metadata.get('exchange_rate', '0'))
                else:
                    total_usd = None
                    exchange_rate = None

                # Detect actual payment method used
                actual_payment_method = self._detect_payment_method(payment_intent)

                logger.info(
                    f"Payment verified - PI: {payment_intent_id}, "
                    f"Method: {actual_payment_method}, "
                    f"Currency: {payment_currency}, "
                    f"Amount: {payment_currency}${paid_amount}"
                )

            except stripe.error.InvalidRequestError:
                logger.error(f"Invalid Payment Intent ID: {payment_intent_id}")
                return Response(
                    {'error': '無效的付款資料'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except stripe.error.StripeError as e:
                logger.error(f"Stripe error: {str(e)}")
                return Response(
                    {'error': '無法驗證付款狀態'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # STEP 2: Check if order already exists (idempotency)
            existing_order = Order.objects.filter(
                stripe_payment_intent_id=payment_intent_id
            ).first()

            if existing_order:
                logger.info(f"Order {existing_order.order_number} already exists")
                return Response(
                    OrderSerializer(existing_order).data,
                    status=status.HTTP_200_OK
                )

            # STEP 3: Validate order data
            serializer = CheckoutSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"Invalid order data: {serializer.errors}")
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # STEP 4: Verify amount matches
            expected_subtotal, expected_delivery, expected_discount, expected_total_hkd = \
                serializer.calculate_order_total()

            if abs(total_hkd - expected_total_hkd) > Decimal('0.01'):
                logger.error(
                    f"Amount mismatch - PI HKD: ${total_hkd}, Expected: ${expected_total_hkd}"
                )
                return Response(
                    {'error': '付款金額不符,請聯絡客服'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # STEP 5: Create order atomically
            try:
                with transaction.atomic():
                    order = serializer.create_order(
                        stripe_payment_intent_id=payment_intent_id,
                        payment_method=actual_payment_method,
                        payment_currency=payment_currency,
                        exchange_rate=exchange_rate,
                        total_usd=total_usd,
                    )

                    order.mark_as_paid(payment_intent_id)
                    order.confirm_order()

                    logger.info(
                        f"Order {order.order_number} created - "
                        f"HK${order.total}, {payment_currency}, Method: {actual_payment_method}"
                    )

            except IntegrityError as e:
                logger.warning(f"IntegrityError (race condition): {str(e)}")
                existing_order = Order.objects.get(stripe_payment_intent_id=payment_intent_id)
                return Response(
                    OrderSerializer(existing_order).data,
                    status=status.HTTP_200_OK
                )

            # STEP 6: Send confirmation email
            try:
                send_order_confirmation_email(order)
            except Exception as e:
                logger.error(f"Failed to send email: {str(e)}", exc_info=True)

            return Response(
                OrderSerializer(order).data,
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.critical(f"Unexpected error: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統錯誤,請聯絡客服'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _detect_payment_method(self, payment_intent):
        """Detect actual payment method from Payment Intent"""
        payment_method_obj = payment_intent.payment_method

        if isinstance(payment_method_obj, str):
            payment_method_details = stripe.PaymentMethod.retrieve(payment_method_obj)
        else:
            payment_method_details = payment_method_obj

        if not payment_method_details:
            return 'card_pay'

        pm_type = payment_method_details.type

        if pm_type == 'alipay':
            return 'alipay'
        elif pm_type == 'wechat_pay':
            return 'wechat_pay'
        elif pm_type == 'card':
            if hasattr(payment_method_details, 'card') and payment_method_details.card:
                wallet = getattr(payment_method_details.card, 'wallet', None)
                if wallet:
                    wallet_type = (
                        wallet.get('type')
                        if isinstance(wallet, dict)
                        else getattr(wallet, 'type', None)
                    )
                    if wallet_type == 'google_pay':
                        return 'google_pay'
                    elif wallet_type == 'apple_pay':
                        return 'apple_pay'

        return 'card_pay'


class OrderDetailView(APIView):
    """Retrieve order details by order number."""

    def get(self, request, order_number):
        try:
            order = Order.objects.prefetch_related('items').get(order_number=order_number)
            serializer = OrderSerializer(order)
            logger.info(f"Order {order_number} details retrieved")
            return Response(serializer.data)

        except Order.DoesNotExist:
            logger.warning(f"Order not found: {order_number}")
            return Response(
                {'error': '訂單不存在'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error retrieving order: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統錯誤'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(APIView):
    """Handle Stripe webhook events"""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

        if not sig_header:
            logger.warning("Webhook received without signature header")
            return HttpResponse('Missing signature', status=400)

        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            logger.error(f"Invalid webhook payload: {e}")
            return HttpResponse('Invalid payload', status=400)
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid webhook signature: {e}")
            return HttpResponse('Invalid signature', status=400)

        event_id = event['id']
        event_type = event['type']

        logger.info(f"Webhook received: {event_type} — {event_id}")

        # Deduplication
        already_processed, _created = StripeWebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={'event_type': event_type}
        )
        if already_processed and not _created:
            logger.info(f"Webhook event {event_id} already processed")
            return HttpResponse(status=200)

        # Dispatch to handlers
        if event_type == 'payment_intent.succeeded':
            self.handle_payment_success(event['data']['object'])
        elif event_type == 'payment_intent.payment_failed':
            self.handle_payment_failure(event['data']['object'])
        elif event_type == 'charge.refunded':
            self.handle_refund(event['data']['object'])

        return HttpResponse(status=200)

    def handle_payment_success(self, payment_intent):
        """Mark order as paid when Stripe confirms payment succeeded"""
        pi_id = payment_intent['id']
        try:
            order = Order.objects.get(stripe_payment_intent_id=pi_id)
            if order.payment_status != 'paid':
                order.mark_as_paid(pi_id)
                logger.info(f"Webhook: marked {order.order_number} as paid")
            else:
                logger.info(f"Webhook: {order.order_number} already paid")
        except Order.DoesNotExist:
            logger.warning(f"Webhook: no order for PI {pi_id}")

    def handle_payment_failure(self, payment_intent):
        pi_id = payment_intent['id']
        try:
            order = Order.objects.get(stripe_payment_intent_id=pi_id)
            if order.payment_status != 'failed':
                order.payment_status = 'failed'
                order.status = 'failed'
                order.save(update_fields=['payment_status', 'status', 'updated_at'])
                logger.warning(f"Webhook: marked {order.order_number} as failed")
        except Order.DoesNotExist:
            logger.warning(f"Webhook: no order for failed PI {pi_id}")

    def handle_refund(self, charge):
        pi_id = charge.get('payment_intent')
        if not pi_id:
            return
        try:
            order = Order.objects.get(stripe_payment_intent_id=pi_id)
            if order.payment_status != 'refunded':
                order.payment_status = 'refunded'
                order.status = 'refunded'
                order.save(update_fields=['payment_status', 'status', 'updated_at'])
                logger.info(f"Webhook: marked {order.order_number} as refunded")
        except Order.DoesNotExist:
            logger.warning(f"Webhook: no order for refunded PI {pi_id}")