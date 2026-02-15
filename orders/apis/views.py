from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import HttpResponse
from django.db import transaction, IntegrityError
from django.utils import timezone
import stripe
import logging
from decimal import Decimal

from currency.models import CurrencyRate
from .serializers import CheckoutSerializer, OrderSerializer
from ..models import Order, StripeWebhookEvent

# Initialize Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

# Configure logging
logger = logging.getLogger(__name__)


class CreatePaymentIntentView(APIView):
    """
    Create a Stripe Payment Intent for the checkout.

    SOLUTION FOR ALIPAY / WECHAT PAY VISIBILITY:
    - Always creates Payment Intent in USD
    - Converts HKD to USD for ALL payment methods
    - This allows Stripe to show AliPay and WeChat Pay in the Payment Element
    - Both AliPay and WeChat Pay are redirect-based: user leaves the site and
      returns via the return_url after completing payment externally.
    - Tracks both HKD and USD amounts for all orders
    """

    def post(self, request):
        try:
            # Validate checkout data first
            serializer = CheckoutSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"Invalid checkout data: {serializer.errors}")
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Calculate total amount using serializer method (in HKD)
            subtotal, delivery_fee, discount, total_hkd = serializer.calculate_order_total()

            # Get exchange rate
            try:
                currency_rate = CurrencyRate.objects.filter(
                    base_currency='USD',
                    target_currency='HKD'
                ).order_by('-created_at').first()

                if not currency_rate:
                    logger.error("No USD to HKD exchange rate found in database")
                    return Response(
                        {'error': '暫時無法處理付款,請稍後再試'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Convert HKD to USD (for ALL payment methods)
                # This is required for AliPay and WeChat Pay which need USD
                exchange_rate = currency_rate.rate
                total_usd = (total_hkd / exchange_rate).quantize(Decimal('0.01'))

            except Exception as e:
                logger.error(f"Error during currency conversion: {str(e)}", exc_info=True)
                return Response(
                    {'error': '貨幣轉換失敗,請稍後再試'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Log calculation details
            logger.info(
                f"Payment Intent - HKD: ${total_hkd}, USD: ${total_usd}, "
                f"Rate: {exchange_rate}, Items: {len(serializer.validated_data['items'])}"
            )

            # Validate amounts
            if total_usd <= 0:
                logger.error(f"Invalid order total: {total_usd} USD")
                return Response(
                    {'error': '訂單金額無效'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if total_usd > Decimal('12820.51'):  # ~$100,000 HKD
                logger.warning(f"Order total exceeds limit: {total_usd} USD")
                return Response(
                    {'error': '訂單金額超過限制'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Convert to cents
            amount_in_cents = int(total_usd * 100)

            # Create Payment Intent in USD
            # USD enables AliPay and WeChat Pay in Stripe's Payment Element.
            # Both are redirect-based payment methods: Stripe will redirect the
            # user to the external app/page, then back to our return_url.
            payment_intent_params = {
                'amount': amount_in_cents,
                'currency': 'usd',  # USD enables AliPay + WeChat Pay
                'automatic_payment_methods': {
                    'enabled': True,
                },
                'metadata': {
                    'customer_name': serializer.validated_data['customer_name'],
                    'customer_email': serializer.validated_data['customer_email'],
                    'customer_phone': serializer.validated_data['customer_phone'],
                    'integration': 'HY Florist',
                    'order_type': 'funeral_flowers',
                    'total_hkd': str(total_hkd),
                    'total_usd': str(total_usd),
                    'exchange_rate': str(exchange_rate),
                    'payment_currency': 'USD',
                }
            }

            # Create Stripe Payment Intent
            payment_intent = stripe.PaymentIntent.create(**payment_intent_params)

            logger.info(
                f"Payment Intent created: {payment_intent.id}, "
                f"Amount: ${total_usd} USD (HK${total_hkd}), "
                f"Methods: {payment_intent.payment_method_types}"
            )

            response_data = {
                'clientSecret': payment_intent.client_secret,
                'amount': float(total_hkd),  # Return HKD for display
                'paymentIntentId': payment_intent.id,
                'currency': 'usd',
                'conversionDetails': {
                    'amountHKD': float(total_hkd),
                    'amountUSD': float(total_usd),
                    'exchangeRate': float(exchange_rate),
                }
            }

            return Response(response_data)

        except stripe.error.CardError as e:
            logger.warning(f"Card error: {e.user_message}")
            return Response(
                {'error': '付款卡問題,請檢查卡片資料'},
                status=status.HTTP_400_BAD_REQUEST
            )

        except stripe.error.RateLimitError as e:
            logger.error(f"Stripe rate limit error: {str(e)}")
            return Response(
                {'error': '請求過於頻繁,請稍後再試'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        except stripe.error.InvalidRequestError as e:
            logger.error(f"Invalid Stripe request: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統錯誤,請稍後再試'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        except stripe.error.AuthenticationError as e:
            logger.critical(f"Stripe authentication error: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統配置錯誤,請聯絡客服'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

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
    Confirm the order after successful payment.
    Creates the order record and sends confirmation email.

    Handles all payments in USD with HKD tracking.

    Redirect-based payment methods (AliPay, WeChat Pay):
    - User is taken to the external payment page by Stripe
    - After completion, Stripe redirects back to our return_url
    - The return page calls this endpoint to confirm the order
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

                # Get payment details
                paid_amount = Decimal(payment_intent.amount) / 100  # USD

                # Extract amounts from metadata
                total_hkd = Decimal(payment_intent.metadata.get('total_hkd', '0'))
                total_usd = Decimal(payment_intent.metadata.get('total_usd', '0'))
                exchange_rate = Decimal(payment_intent.metadata.get('exchange_rate', '0'))

                # -------------------------------------------------------
                # Detect payment method
                # AliPay  → pm_type == 'alipay'
                # WeChat  → pm_type == 'wechat_pay'
                # Cards   → pm_type == 'card', then check wallet sub-type
                # -------------------------------------------------------
                actual_payment_method = 'card_pay'
                payment_method_obj = payment_intent.payment_method

                if isinstance(payment_method_obj, str):
                    payment_method_details = stripe.PaymentMethod.retrieve(payment_method_obj)
                else:
                    payment_method_details = payment_method_obj

                if payment_method_details:
                    pm_type = payment_method_details.type

                    if pm_type == 'alipay':
                        actual_payment_method = 'alipay'

                    elif pm_type == 'wechat_pay':
                        # WeChat Pay is a redirect-based method, same as AliPay.
                        # User is redirected to WeChat (app or web QR), completes
                        # payment there, then redirected back to our return_url.
                        actual_payment_method = 'wechat_pay'

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
                                    actual_payment_method = 'google_pay'
                                elif wallet_type == 'apple_pay':
                                    actual_payment_method = 'apple_pay'

                logger.info(
                    f"Payment verified - PI: {payment_intent_id}, "
                    f"Method: {actual_payment_method}, "
                    f"Amount: ${paid_amount} USD (HK${total_hkd})"
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

            # STEP 4: Verify amount matches (allow 1 cent difference for rounding)
            subtotal, delivery_fee, discount, expected_total_hkd = serializer.calculate_order_total()

            if abs(paid_amount - total_usd) > Decimal('0.01'):
                logger.error(
                    f"Amount mismatch - Paid: ${paid_amount} USD, Expected: ${total_usd} USD"
                )
                return Response(
                    {'error': f'付款金額不符,請聯絡客服'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # STEP 5: Create order atomically
            try:
                with transaction.atomic():
                    order = serializer.create_order(
                        stripe_payment_intent_id=payment_intent_id,
                        payment_method=actual_payment_method,
                        payment_currency='USD',
                        exchange_rate=exchange_rate,
                        total_usd=total_usd,
                    )

                    order.mark_as_paid(payment_intent_id)
                    order.confirm_order()

                    logger.info(
                        f"Order {order.order_number} created - "
                        f"HK${order.total}, US${total_usd}, Method: {actual_payment_method}"
                    )

            except IntegrityError as e:
                # Race condition: another request already created the order
                logger.warning(f"IntegrityError (race condition): {str(e)}")
                existing_order = Order.objects.get(stripe_payment_intent_id=payment_intent_id)
                return Response(
                    OrderSerializer(existing_order).data,
                    status=status.HTTP_200_OK
                )

            # STEP 6: Send confirmation email (non-blocking on failure)
            try:
                self.send_confirmation_email(order)
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

    def send_confirmation_email(self, order):
        """Send order confirmation email to customer"""
        try:
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

            logger.info(f"Confirmation email sent for order {order.order_number}")

        except Exception as e:
            raise Exception(f"Email sending failed: {str(e)}")


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
    """
    Handle Stripe webhook events.

    Stripe sends webhooks for all payment events, including redirect-based
    methods like AliPay and WeChat Pay. This provides a server-side safety
    net in case the user closes the browser before the return page runs.
    """

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

        # Deduplication: safe get_or_create prevents double-processing
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
        """
        Marks the order as paid when Stripe confirms payment succeeded.
        This is especially important for AliPay and WeChat Pay where the
        user might close the browser before hitting our return_url.
        """
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