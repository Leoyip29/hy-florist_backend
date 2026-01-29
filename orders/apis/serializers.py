from rest_framework import serializers

from orders.models import OrderItem, Order
from products.models import Product
from decimal import Decimal


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
        read_only_fields = ['order_number', 'created_at']


class CheckoutSerializer(serializers.Serializer):
    """
    Serializer for checkout process.
    Validates customer information and cart items.
    """

    # Customer Information
    customer_name = serializers.CharField(max_length=255)
    customer_email = serializers.EmailField()
    customer_phone = serializers.CharField(max_length=20)

    # Delivery Information
    delivery_address = serializers.CharField()
    delivery_notes = serializers.CharField(required=False, allow_blank=True)

    # Payment Information
    payment_method = serializers.ChoiceField(
        choices=['stripe', 'apple_pay', 'payme'],
        default='stripe'
    )

    # Cart Items
    items = OrderItemSerializer(many=True)

    def validate_items(self, items):
        """Validate that all products exist and are available"""
        if not items:
            raise serializers.ValidationError("Cart cannot be empty")

        for item in items:
            try:
                product = Product.objects.get(id=item['product_id'])
                # You can add stock validation here if needed
                # if product.stock < item['quantity']:
                #     raise serializers.ValidationError(f"{product.name} is out of stock")
            except Product.DoesNotExist:
                raise serializers.ValidationError(
                    f"Product with id {item['product_id']} does not exist"
                )

        return items


    def create_order(self, stripe_payment_intent_id=None):
        """
        Create an order with order items from validated data.
        This is called after payment is confirmed.
        """
        validated_data = self.validated_data

        # Calculate totals
        subtotal = Decimal('0.00')
        order_items_data = []

        for item_data in validated_data['items']:
            product = Product.objects.get(id=item_data['product_id'])
            quantity = item_data['quantity']
            price = Decimal(str(product.price))
            line_total = price * quantity

            subtotal += line_total

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

        # Create order
        delivery_fee = Decimal('0.00')  # You can add delivery fee logic here
        discount = Decimal('0.00')  # You can add discount logic here
        total = subtotal + delivery_fee - discount

        order = Order.objects.create(
            customer_name=validated_data['customer_name'],
            customer_email=validated_data['customer_email'],
            customer_phone=validated_data['customer_phone'],
            delivery_address=validated_data['delivery_address'],
            delivery_notes=validated_data.get('delivery_notes', ''),
            payment_method=validated_data['payment_method'],
            stripe_payment_intent_id=stripe_payment_intent_id,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            discount=discount,
            total=total,
            payment_status='pending',
        )

        # Create order items
        for item_data in order_items_data:
            OrderItem.objects.create(order=order, **item_data)

        return order