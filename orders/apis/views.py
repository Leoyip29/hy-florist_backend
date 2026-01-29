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
import stripe
import json
from datetime import datetime
from .serializers import CheckoutSerializer, OrderSerializer
from ..models import Order

# Initialize Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


class CreatePaymentIntentView(APIView):
    """
    Create a Stripe Payment Intent for the checkout.
    This is called before the user enters payment details.
    """

    def post(self, request):
        try:
            # Validate checkout data first
            serializer = CheckoutSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Calculate total amount (in cents for Stripe)
            from decimal import Decimal
            subtotal = Decimal('0.00')

            for item in serializer.validated_data['items']:
                from products.models import Product
                product = Product.objects.get(id=item['product_id'])
                subtotal += Decimal(str(product.price)) * item['quantity']

            # Add delivery fee and discount logic here if needed
            delivery_fee = Decimal('0.00')
            discount = Decimal('0.00')
            total = subtotal + delivery_fee - discount

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
                }
            )

            return Response({
                'clientSecret': payment_intent.client_secret,
                'amount': float(total),
            })

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ConfirmOrderView(APIView):
    """
    Confirm the order after successful payment.
    Creates the order record and sends confirmation email.
    """

    def post(self, request):
        try:
            payment_intent_id = request.data.get('payment_intent_id')

            if not payment_intent_id:
                return Response(
                    {'error': 'Payment Intent ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )


            # Validate and create order
            serializer = CheckoutSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create order
            order = serializer.create_order(stripe_payment_intent_id=payment_intent_id)
            order.payment_status = 'paid'
            order.paid_at = datetime.now()
            order.save()

            # Send confirmation email
            self.send_confirmation_email(order)

            # Return order details
            order_serializer = OrderSerializer(order)
            return Response(order_serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': str(e)},
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
            }

            # Render HTML and plain text versions
            html_message = render_to_string(
                'email/order_confirmation.html',
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
        except Exception as e:
            # Log error but don't fail the order creation
            print(f"Failed to send confirmation email: {str(e)}")


class OrderDetailView(APIView):
    """Retrieve order details by order number"""

    def get(self, request, order_number):
        try:
            order = Order.objects.get(order_number=order_number)
            serializer = OrderSerializer(order)
            return Response(serializer.data)
        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(APIView):
    """
    Handle Stripe webhook events.
    This is called by Stripe when payment events occur.
    """

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError:
            return HttpResponse(status=400)

        # Handle the event
        if event['type'] == 'payment_intent.succeeded':
            payment_intent = event['data']['object']
            self.handle_payment_success(payment_intent)

        elif event['type'] == 'payment_intent.payment_failed':
            payment_intent = event['data']['object']
            self.handle_payment_failure(payment_intent)

        return HttpResponse(status=200)

    def handle_payment_success(self, payment_intent):
        """Handle successful payment"""
        try:
            order = Order.objects.get(
                stripe_payment_intent_id=payment_intent['id']
            )
            order.payment_status = 'paid'
            order.paid_at = datetime.now()
            order.save()
        except Order.DoesNotExist:
            pass

    def handle_payment_failure(self, payment_intent):
        """Handle failed payment"""
        try:
            order = Order.objects.get(
                stripe_payment_intent_id=payment_intent['id']
            )
            order.payment_status = 'failed'
            order.save()
        except Order.DoesNotExist:
            pass