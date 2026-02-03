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

from .serializers import CheckoutSerializer, OrderSerializer
from ..models import Order

# Initialize Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

# Configure logging
logger = logging.getLogger(__name__)


class CreatePaymentIntentView(APIView):
    """
    Create a Stripe Payment Intent for the checkout.
    This is called before the user enters payment details.

    Security features:
    - Server-side amount calculation
    - Input validation via serializer
    - Proper error handling and logging
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

            # Calculate total amount using serializer method
            subtotal, delivery_fee, discount, total = serializer.calculate_order_total()

            # Log calculation details
            logger.info(
                f"Payment Intent calculation - Subtotal: HK${subtotal}, "
                f"Delivery: HK${delivery_fee}, Discount: HK${discount}, "
                f"Total: HK${total}, Items: {len(serializer.validated_data['items'])}"
            )

            # Validate total is reasonable
            if total <= 0:
                logger.error(f"Invalid order total: {total}")
                return Response(
                    {'error': '訂單金額無效'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if total > Decimal('100000.00'):  # HK$100,000 limit
                logger.warning(f"Order total exceeds limit: {total}")
                return Response(
                    {'error': '訂單金額超過限制'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Convert to cents (Stripe requires amount in smallest currency unit)
            amount_in_cents = int(total * 100)

            # Create Stripe Payment Intent
            payment_intent = stripe.PaymentIntent.create(
                amount=amount_in_cents,
                currency='hkd',
                payment_method_types=['card'],
                metadata={
                    'customer_name': serializer.validated_data['customer_name'],
                    'customer_email': serializer.validated_data['customer_email'],
                    'integration': 'HY Florist',
                }
            )

            logger.info(f"Payment Intent created: {payment_intent.id} for amount: HK${total}")

            return Response({
                'clientSecret': payment_intent.client_secret,
                'amount': float(total),
            })

        except stripe.error.CardError as e:
            # Card-specific error
            logger.warning(f"Card error during payment intent creation: {e.user_message}")
            return Response(
                {'error': '付款卡問題，請檢查卡片資料'},
                status=status.HTTP_400_BAD_REQUEST
            )

        except stripe.error.RateLimitError as e:
            logger.error(f"Stripe rate limit error: {str(e)}")
            return Response(
                {'error': '請求過於頻繁，請稍後再試'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        except stripe.error.InvalidRequestError as e:
            logger.error(f"Invalid Stripe request: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統錯誤，請稍後再試'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        except stripe.error.AuthenticationError as e:
            logger.critical(f"Stripe authentication error: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統配置錯誤，請聯絡客服'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {str(e)}", exc_info=True)
            return Response(
                {'error': '付款系統錯誤，請稍後再試'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        except Exception as e:
            logger.critical(f"Unexpected error in CreatePaymentIntent: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統錯誤，請聯絡客服'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ConfirmOrderView(APIView):
    """
    Confirm the order after successful payment.
    Creates the order record and sends confirmation email.

    Security features:
    - Payment Intent verification with Stripe
    - Idempotency (duplicate order prevention)
    - Amount verification
    - Atomic database transactions
    - Comprehensive error handling
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
                payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

                if payment_intent.status != 'succeeded':
                    logger.warning(
                        f"Payment Intent {payment_intent_id} status is {payment_intent.status}, not succeeded"
                    )
                    return Response(
                        {'error': '付款尚未完成'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                paid_amount = Decimal(payment_intent.amount) / 100  # Convert cents to HKD

            except stripe.error.InvalidRequestError:
                logger.error(f"Invalid Payment Intent ID: {payment_intent_id}")
                return Response(
                    {'error': '無效的付款資料'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except stripe.error.StripeError as e:
                logger.error(f"Stripe error verifying payment: {str(e)}")
                return Response(
                    {'error': '無法驗證付款狀態'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # STEP 2: Check if order already exists (idempotency)
            existing_order = Order.objects.filter(
                stripe_payment_intent_id=payment_intent_id
            ).first()

            if existing_order:
                logger.info(
                    f"Order {existing_order.order_number} already exists for Payment Intent {payment_intent_id}"
                )
                return Response(
                    OrderSerializer(existing_order).data,
                    status=status.HTTP_200_OK  # Not 201, because not newly created
                )

            # STEP 3: Validate order data
            serializer = CheckoutSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"Invalid order data for PI {payment_intent_id}: {serializer.errors}")
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Log the cart items being confirmed
            items_summary = [
                f"Product {item['product_id']}: qty {item['quantity']}"
                for item in serializer.validated_data['items']
            ]
            logger.info(
                f"Confirming order for PI {payment_intent_id}. Items: {', '.join(items_summary)}"
            )

            # STEP 4: Verify amount matches
            subtotal, delivery_fee, discount, expected_total = serializer.calculate_order_total()

            # Log both amounts for debugging
            logger.info(
                f"Amount verification - Payment Intent: {payment_intent_id}, "
                f"Paid: HK${paid_amount}, Expected: HK${expected_total}, "
                f"Subtotal: HK${subtotal}, Delivery: HK${delivery_fee}, Discount: HK${discount}"
            )

            # Allow 1 cent difference for rounding
            if abs(paid_amount - expected_total) > Decimal('0.01'):
                logger.error(
                    f"Amount mismatch - Paid: {paid_amount}, Expected: {expected_total}, "
                    f"Difference: {abs(paid_amount - expected_total)}, "
                    f"Payment Intent: {payment_intent_id}"
                )
                return Response(
                    {'error': f'付款金額不符 (已付: HK${paid_amount}, 應付: HK${expected_total})，請聯絡客服'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # STEP 5: Create order atomically
            try:
                with transaction.atomic():
                    order = serializer.create_order(
                        stripe_payment_intent_id=payment_intent_id
                    )

                    # Mark as paid
                    order.mark_as_paid(payment_intent_id)
                    order.confirm_order()

                    logger.info(
                        f"Order {order.order_number} created successfully. "
                        f"Payment Intent: {payment_intent_id}, Amount: HK${order.total}"
                    )

            except IntegrityError as e:
                # Race condition: Another request created the order
                logger.warning(
                    f"IntegrityError creating order for Payment Intent {payment_intent_id}: {str(e)}"
                )
                existing_order = Order.objects.get(stripe_payment_intent_id=payment_intent_id)
                return Response(
                    OrderSerializer(existing_order).data,
                    status=status.HTTP_200_OK
                )

            # STEP 6: Send confirmation email (outside transaction)
            try:
                self.send_confirmation_email(order)
            except Exception as e:
                # Log error but don't fail the order
                logger.error(
                    f"Failed to send confirmation email for order {order.order_number}: {str(e)}",
                    exc_info=True
                )

            # Return order details
            return Response(
                OrderSerializer(order).data,
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.critical(
                f"Unexpected error in ConfirmOrder: {str(e)}",
                exc_info=True
            )
            return Response(
                {'error': '系統錯誤，請聯絡客服'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def send_confirmation_email(self, order):
        """Send order confirmation email to customer"""
        try:
            # Prepare context for email template
            context = {
                'order': order,
                'items': order.items.all(),
                'company_name': 'HY Florist',
                'support_email': settings.DEFAULT_FROM_EMAIL,
                'year': timezone.now().year,
            }

            # Render HTML and plain text versions
            html_message = render_to_string(
                'emails/order_confirmation.html',
                context
            )
            plain_message = strip_tags(html_message)

            # Send email
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
            # Re-raise to be caught by caller
            raise Exception(f"Email sending failed: {str(e)}")


class OrderDetailView(APIView):
    """
    Retrieve order details by order number.

    Security: No authentication required for guest checkout,
    but order number is difficult to guess (UUID-based).
    """

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
            logger.error(f"Error retrieving order {order_number}: {str(e)}", exc_info=True)
            return Response(
                {'error': '系統錯誤'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(APIView):
    """
    Handle Stripe webhook events.
    This is called by Stripe when payment events occur.

    Security features:
    - Webhook signature verification
    - CSRF exemption (verified via signature)
    - Idempotent order updates
    - Comprehensive logging

    Note: This provides redundancy in case frontend confirmation fails.
    """

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

        if not sig_header:
            logger.warning("Webhook received without signature header")
            return HttpResponse('Missing signature', status=400)

        # Verify webhook signature
        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            logger.error(f"Invalid webhook payload: {str(e)}")
            return HttpResponse('Invalid payload', status=400)
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid webhook signature: {str(e)}")
            return HttpResponse('Invalid signature', status=400)

        # Log webhook event
        logger.info(f"Webhook received: {event['type']} - {event['id']}")

        # Handle the event
        if event['type'] == 'payment_intent.succeeded':
            payment_intent = event['data']['object']
            self.handle_payment_success(payment_intent)

        elif event['type'] == 'payment_intent.payment_failed':
            payment_intent = event['data']['object']
            self.handle_payment_failure(payment_intent)

        elif event['type'] == 'charge.refunded':
            charge = event['data']['object']
            self.handle_refund(charge)

        return HttpResponse(status=200)

    def handle_payment_success(self, payment_intent):
        """
        Handle successful payment.
        Idempotent - safe to call multiple times.
        """
        payment_intent_id = payment_intent['id']

        try:
            order = Order.objects.get(stripe_payment_intent_id=payment_intent_id)

            if order.payment_status != 'paid':
                order.mark_as_paid(payment_intent_id)
                logger.info(
                    f"Webhook: Marked order {order.order_number} as paid via webhook"
                )
            else:
                logger.info(
                    f"Webhook: Order {order.order_number} already marked as paid"
                )

        except Order.DoesNotExist:
            logger.warning(
                f"Webhook: No order found for Payment Intent {payment_intent_id}. "
                "Order may not be created yet (frontend confirmation pending)."
            )

    def handle_payment_failure(self, payment_intent):
        """Handle failed payment"""
        payment_intent_id = payment_intent['id']

        try:
            order = Order.objects.get(stripe_payment_intent_id=payment_intent_id)

            if order.payment_status != 'failed':
                order.payment_status = 'failed'
                order.status = 'failed'
                order.save(update_fields=['payment_status', 'status', 'updated_at'])

                logger.warning(
                    f"Webhook: Marked order {order.order_number} as failed"
                )
        except Order.DoesNotExist:
            logger.warning(
                f"Webhook: No order found for failed Payment Intent {payment_intent_id}"
            )

    def handle_refund(self, charge):
        """Handle refund event"""
        payment_intent_id = charge.get('payment_intent')

        if not payment_intent_id:
            return

        try:
            order = Order.objects.get(stripe_payment_intent_id=payment_intent_id)

            if order.payment_status != 'refunded':
                order.payment_status = 'refunded'
                order.status = 'refunded'
                order.save(update_fields=['payment_status', 'status', 'updated_at'])

                logger.info(
                    f"Webhook: Marked order {order.order_number} as refunded"
                )
        except Order.DoesNotExist:
            logger.warning(
                f"Webhook: No order found for refunded Payment Intent {payment_intent_id}"
            )