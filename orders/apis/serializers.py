from rest_framework import serializers

from orders.models import OrderItem, Order
from products.models import Product
from decimal import Decimal
from datetime import date, timedelta


class OrderItemSerializer(serializers.Serializer):
    """Serializer for creating order items"""
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class OrderItemDetailSerializer(serializers.ModelSerializer):
    """Serializer for displaying order item details"""

    class Meta:
        model = OrderItem
        fields = [
            'id',
            'product_name',
            'product_price',
            'quantity',
            'line_total',
        ]


class OrderSerializer(serializers.ModelSerializer):
    """Serializer for displaying order details"""
    items = OrderItemDetailSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            'id',
            'order_number',
            'customer_name',
            'customer_email',
            'customer_phone',
            'delivery_address',
            'delivery_date',
            'delivery_notes',
            'payment_method',
            'payment_status',
            'subtotal',
            'delivery_fee',
            'discount',
            'total',
            'created_at',
            'items',
        ]
        read_only_fields = ['order_number', 'created_at','paid_at']


class CheckoutSerializer(serializers.Serializer):
    """
    Serializer for checkout process.
    Validates customer information and cart items.
    """

    # Customer Information
    customer_name = serializers.CharField(
        max_length=255,
        min_length=2,
        error_messages={
            'min_length': 'Name must be at least 2 characters',
            'required': 'Name is required'
        }
    )
    customer_email = serializers.EmailField(
        error_messages={
            'invalid': 'Please provide a valid email address',
            'required': 'Email is required'
        }
    )
    customer_phone = serializers.CharField(
        max_length=20,
        min_length=8,
        error_messages={
            'min_length': 'Phone number must be at least 8 digits',
            'required': 'Phone number is required'
        }
    )

    # Delivery Information
    delivery_address = serializers.CharField(
        min_length=10,
        error_messages={
            'min_length': 'Please provide a complete address',
            'required': 'Delivery address is required'
        }
    )

    delivery_date = serializers.DateField(
        error_messages={
            'invalid': 'Please provide a valid delivery date',
            'required': 'Delivery date is required'
        }
    )

    delivery_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500
    )

    # Payment Information
    payment_method = serializers.ChoiceField(
        choices=['stripe', 'apple_pay', 'payme'],
        default='stripe'
    )

    # Cart Items
    items = OrderItemSerializer(many=True)

    def validate_delivery_date(self, value):
        """
        Validate that delivery date is at least 3 days in advance.
        """
        today = date.today()
        min_delivery_date = today + timedelta(days=2)

        if value < min_delivery_date:
            raise serializers.ValidationError(
                f"送貨日期必須至少提前3天。最早可選日期為 {min_delivery_date.strftime('%Y-%m-%d')}"
            )

        # Optional: Add maximum advance order period (e.g., 90 days)
        max_delivery_date = today + timedelta(days=90)
        if value > max_delivery_date:
            raise serializers.ValidationError(
                "送貨日期不能超過90天後"
            )

        return value

    def validate_items(self, items):
        """Validate that all products exist and are available"""
        if not items:
            raise serializers.ValidationError("Cart cannot be empty")

        if len(items) > 50:
            raise serializers.ValidationError("Maximum 50 items per order")

        product_ids = [item['product_id'] for item in items]

        # Check for duplicate products in cart
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError("Duplicate products in cart")

        # Validate all products exist
        existing_products = Product.objects.filter(id__in=product_ids)
        existing_ids = set(existing_products.values_list('id', flat=True))

        missing_ids = set(product_ids) - existing_ids
        if missing_ids:
            raise serializers.ValidationError(
                f"Products not found: {', '.join(map(str, missing_ids))}"
            )

        # Validate quantities are reasonable
        for item in items:
            if item['quantity'] > 100:
                raise serializers.ValidationError(
                    f"Maximum quantity is 100 per item"
                )

        return items

    def calculate_order_total(self):
        """
        Calculate order total from validated items.
        Returns (subtotal, delivery_fee, discount, total)

        IMPORTANT: This calculation MUST match the one in CreatePaymentIntentView
        to avoid amount mismatch errors.
        """
        subtotal = Decimal('0.00')

        for item_data in self.validated_data['items']:
            product = Product.objects.get(id=item_data['product_id'])
            quantity = item_data['quantity']
            price = Decimal(str(product.price))
            subtotal += price * quantity

        # Business logic for fees/discounts
        # MUST MATCH CreatePaymentIntentView calculation
        delivery_fee = Decimal('0.00')
        discount = Decimal('0.00')

        # Currently: No delivery fee, no discount
        # If you want to add fees/discounts, update BOTH places:
        # 1. Here (serializers.py)
        # 2. CreatePaymentIntentView (views.py)

        total = subtotal + delivery_fee - discount

        return subtotal, delivery_fee, discount, total


    def create_order(self, stripe_payment_intent_id=None):
        """
        Create an order with order items from validated data.
        This is called after payment is confirmed.
        """
        from django.db import transaction
        validated_data = self.validated_data

        # Calculate totals
        subtotal, delivery_fee, discount, total = self.calculate_order_total()
        order_items_data = []

        for item_data in validated_data['items']:
            product = Product.objects.get(id=item_data['product_id'])
            quantity = item_data['quantity']
            price = Decimal(str(product.price))
            line_total = price * quantity

            # Get primary image URL
            primary_image = product.images.filter(is_primary=True).first()
            image_url = primary_image.url if primary_image else None

            order_items_data.append({
                'product': product,
                'product_name': product.name,
                'product_price': price,
                'quantity': quantity,
                'line_total': line_total,
            })

        # Create order and items atomically
        with transaction.atomic():
            order = Order.objects.create(
                customer_name=validated_data['customer_name'],
                customer_email=validated_data['customer_email'],
                customer_phone=validated_data['customer_phone'],
                delivery_address=validated_data['delivery_address'],
                delivery_notes=validated_data.get('delivery_notes', ''),
                delivery_date=validated_data.get('delivery_date', ''),
                payment_method=validated_data['payment_method'],
                stripe_payment_intent_id=stripe_payment_intent_id,
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                discount=discount,
                total=total,
                payment_status='pending',
                status='pending',
            )

            # Create order items
            for item_data in order_items_data:
                OrderItem.objects.create(order=order, **item_data)

        return order




