from rest_framework import serializers

from orders.models import OrderItem, Order
from products.models import Product
from decimal import Decimal
from datetime import date, timedelta
import re


class OrderItemSerializer(serializers.Serializer):
    """Serializer for creating order items"""
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    selected_option_id = serializers.IntegerField(required=False, allow_null=True)


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
            'option_name',
        ]


class OrderSerializer(serializers.ModelSerializer):
    """Serializer for displaying order details"""
    items = OrderItemDetailSerializer(many=True, read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display_name', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id',
            'order_number',
            'customer_name',
            'customer_email',
            'customer_phone',
            'deceased_name',
            'delivery_address',
            'delivery_region',
            'delivery_district',
            'delivery_date',
            'delivery_notes',
            'payment_method',
            'payment_method_display',
            'payment_status',
            'payment_currency',
            'exchange_rate',
            'total_usd',
            'subtotal',
            'delivery_fee',
            'discount',
            'total',
            'language',
            'created_at',
            'items',
        ]
        read_only_fields = ['order_number', 'created_at', 'paid_at']


class CheckoutSerializer(serializers.Serializer):
    """
    Serializer for checkout process.
    Validates customer information and cart items with bilingual error messages.
    """

    ERROR_MESSAGES = {
        'en': {
            'customer_name': {
                'required': 'Please enter your name',
                'min_length': 'Name must be at least 2 characters',
                'max_length': 'Name is too long',
            },
            'customer_email': {
                'required': 'Please enter your email address',
                'invalid': 'Please enter a valid email address',
            },
            'customer_phone': {
                'required': 'Please enter your phone number',
                'min_length': 'Phone number must be at least 8 digits',
                'max_length': 'Phone number is too long',
                'digit': 'Phone number must contain only digits',
            },
            'deceased_name': {
                'required': 'Please enter the deceased name',
                'min_length': "Deceased's name must be at least 2 characters",
            },
            'delivery_address': {
                'min_length': 'Please provide a complete delivery address',
            },
            'delivery_region': {
                'required': 'Please select a location type',
            },
            'delivery_district': {
                'required': 'Please select a delivery location',
            },
            'delivery_date': {
                'required': 'Please select a delivery date',
                'invalid': 'Please provide a valid delivery date',
                'min_days': 'Delivery date must be at least 3 days in advance. Earliest available date: {date}',
                'max_days': 'Delivery date cannot be more than 90 days in advance',
            },
            'items': {
                'empty': 'Cart cannot be empty',
                'max_items': 'Maximum 50 items per order',
                'duplicate': 'Duplicate products in cart',
                'not_found': 'Some products are no longer available',
                'max_quantity': 'Maximum quantity is 100 per item',
            },
        },
        'zh-HK': {
            'customer_name': {
                'required': '請輸入您的姓名',
                'min_length': '姓名至少需要2個字符',
                'max_length': '姓名太長',
            },
            'customer_email': {
                'required': '請輸入電郵地址',
                'invalid': '請輸入有效的電郵地址',
            },
            'customer_phone': {
                'required': '請輸入電話號碼',
                'min_length': '電話號碼至少需要8位數字',
                'max_length': '電話號碼太長',
                'digit': '電話號碼必須只包含數字',
            },
            'deceased_name': {
                'required': '請輸入先人的姓名',
                'min_length': '先人姓名至少需要2個字符',
            },
            'delivery_address': {
                'min_length': '請輸入完整的送貨地址',
            },
            'delivery_region': {
                'required': '請選擇地點類別',
            },
            'delivery_district': {
                'required': '請選擇送貨地點',
            },
            'delivery_date': {
                'required': '請選擇送貨日期',
                'invalid': '請輸入有效的送貨日期',
                'min_days': '送貨日期必須至少提前3天。最早可選日期為 {date}',
                'max_days': '送貨日期不能超過90天後',
            },
            'items': {
                'empty': '購物車不能為空',
                'max_items': '每筆訂單最多50件商品',
                'duplicate': '購物車中有重複的商品',
                'not_found': '部分商品已下架',
                'max_quantity': '每件商品最多100件',
            },
        },
    }

    def _get_error(self, field, error_type, **kwargs):
        """Get localized error message"""
        language = self.initial_data.get('language', 'zh-HK') if hasattr(self, 'initial_data') else 'zh-HK'
        messages = self.ERROR_MESSAGES.get(language, self.ERROR_MESSAGES['zh-HK'])

        if field in messages and error_type in messages[field]:
            msg = messages[field][error_type]
            if kwargs:
                return msg.format(**kwargs)
            return msg

        # Fallback to English
        messages = self.ERROR_MESSAGES['en']
        if field in messages and error_type in messages[field]:
            msg = messages[field][error_type]
            if kwargs:
                return msg.format(**kwargs)
            return msg

        return f"Validation error for {field}"

    # Customer Information
    customer_name = serializers.CharField(
        max_length=255,
        min_length=2,
        required=True,
        error_messages={
            'required': '',
            'min_length': '',
            'max_length': '',
            'blank': '',
        },
    )
    customer_email = serializers.CharField(
        max_length=255,
        required=True,
        error_messages={
            'required': '',
            'blank': '',
        },
    )
    customer_phone = serializers.CharField(
        max_length=20,
        required=True,
        error_messages={
            'required': '',
            'max_length': '',
            'blank': '',
        },
    )

    # Deceased person's name
    deceased_name = serializers.CharField(
        max_length=255,
        min_length=2,
        required=True,
    )

    # Delivery Information
    delivery_address = serializers.CharField(
        min_length=10,
        required=False,
        allow_blank=True,
    )

    delivery_region = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100
    )

    delivery_district = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100
    )

    delivery_date = serializers.DateField(
        required=True,
    )

    delivery_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500
    )

    # Payment Information
    payment_method = serializers.ChoiceField(
        choices=['card_pay', 'apple_pay', 'google_pay', 'payme', 'whatsapp', 'alipay', 'wechat_pay'],
        default='card_pay'
    )

    # Language preference
    language = serializers.ChoiceField(
        choices=['zh-HK', 'en'],
        default='zh-HK',
        required=False,
    )

    # Cart Items
    items = OrderItemSerializer(many=True)

    def validate_customer_name(self, value):
        value = value.strip() if value else ""
        if not value:
            raise serializers.ValidationError(self._get_error('customer_name', 'required'))
        if len(value) < 2:
            raise serializers.ValidationError(self._get_error('customer_name', 'min_length'))
        if len(value) > 255:
            raise serializers.ValidationError(self._get_error('customer_name', 'max_length'))
        return value

    def validate_customer_email(self, value):
        value = value.strip() if value else ""
        if not value:
            raise serializers.ValidationError(self._get_error('customer_email', 'required'))
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', value):
            raise serializers.ValidationError(self._get_error('customer_email', 'invalid'))
        return value

    def validate_customer_phone(self, value):
        value = value.strip() if value else ""
        cleaned = re.sub(r'[\s\-\(\)]', '', value)
        if not value:
            raise serializers.ValidationError(self._get_error('customer_phone', 'required'))
        if not cleaned.isdigit():
            raise serializers.ValidationError(self._get_error('customer_phone', 'digit'))
        if len(cleaned) < 8:
            raise serializers.ValidationError(self._get_error('customer_phone', 'min_length'))
        if len(value) > 20:
            raise serializers.ValidationError(self._get_error('customer_phone', 'max_length'))
        return value

    def validate_deceased_name(self, value):
        value = value.strip() if value else ""
        if not value:
            raise serializers.ValidationError(self._get_error('deceased_name', 'required'))
        if len(value) < 2:
            raise serializers.ValidationError(self._get_error('deceased_name', 'min_length'))
        return value

    def validate_delivery_region(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError(self._get_error('delivery_region', 'required'))
        return value

    def validate_delivery_district(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError(self._get_error('delivery_district', 'required'))
        return value

    def validate_delivery_date(self, value):
        import re
        if value is None:
            raise serializers.ValidationError(self._get_error('delivery_date', 'required'))

        today = date.today()
        min_delivery_date = today + timedelta(days=2)

        if value < min_delivery_date:
            raise serializers.ValidationError(
                self._get_error('delivery_date', 'min_days', date=min_delivery_date.strftime('%Y-%m-%d'))
            )

        max_delivery_date = today + timedelta(days=90)
        if value > max_delivery_date:
            raise serializers.ValidationError(self._get_error('delivery_date', 'max_days'))

        return value

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError(self._get_error('items', 'empty'))

        if len(items) > 50:
            raise serializers.ValidationError(self._get_error('items', 'max_items'))

        product_ids = [item['product_id'] for item in items]

        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(self._get_error('items', 'duplicate'))

        existing_products = Product.objects.filter(id__in=product_ids)
        existing_ids = set(existing_products.values_list('id', flat=True))

        missing_ids = set(product_ids) - existing_ids
        if missing_ids:
            raise serializers.ValidationError(self._get_error('items', 'not_found'))

        for item in items:
            if item['quantity'] > 100:
                raise serializers.ValidationError(self._get_error('items', 'max_quantity'))

        return items

    def calculate_order_total(self):
        subtotal = Decimal('0.00')
        has_board_set = False

        for item_data in self.validated_data['items']:
            product = Product.objects.get(id=item_data['product_id'])
            quantity = item_data['quantity']

            # Get selected option if provided
            selected_option_id = item_data.get('selected_option_id')
            if selected_option_id:
                try:
                    from products.models import ProductOption
                    option = ProductOption.objects.get(id=selected_option_id, product=product)
                    price = Decimal(str(product.price)) + Decimal(str(option.price_adjustment))
                except ProductOption.DoesNotExist:
                    price = Decimal(str(product.price))
            else:
                price = Decimal(str(product.price))

            subtotal += price * quantity

            # Check if product has board set category
            for cat in product.categories.all():
                if 'board set' in cat.name.lower() or 'board sets' in cat.name.lower() or '花牌套餐' in cat.name:
                    has_board_set = True

        total_item_count = sum(item_data['quantity'] for item_data in self.validated_data['items'])

        # Free delivery if: 8+ items, OR contains board set
        if has_board_set:
            delivery_fee = Decimal('0.00')
        elif total_item_count >= 8:
            delivery_fee = Decimal('0.00')
        elif total_item_count <= 1:
            delivery_fee = Decimal('200.00')
        else:
            delivery_fee = Decimal('200.00') + Decimal('30.00') * (total_item_count - 1)

        discount = Decimal('0.00')
        total = subtotal + delivery_fee - discount

        return subtotal, delivery_fee, discount, total

    def create_order(self, stripe_payment_intent_id=None, payment_method=None,
                     payment_currency='HKD', exchange_rate=None, total_usd=None):
        from django.db import transaction
        validated_data = self.validated_data

        subtotal, delivery_fee, discount, total = self.calculate_order_total()
        order_items_data = []

        for item_data in validated_data['items']:
            product = Product.objects.get(id=item_data['product_id'])
            quantity = item_data['quantity']
            
            # Get selected option if provided
            option_name = None
            selected_option_id = item_data.get('selected_option_id')
            if selected_option_id:
                try:
                    from products.models import ProductOption
                    option = ProductOption.objects.get(id=selected_option_id, product=product)
                    option_name = option.name
                    # Add price adjustment
                    price = Decimal(str(product.price)) + Decimal(str(option.price_adjustment))
                except ProductOption.DoesNotExist:
                    price = Decimal(str(product.price))
            else:
                price = Decimal(str(product.price))
            
            line_total = price * quantity

            order_items_data.append({
                'product': product,
                'product_name': product.name,
                'product_price': price,
                'quantity': quantity,
                'line_total': line_total,
                'option_name': option_name,
            })

        final_payment_method = payment_method or validated_data.get('payment_method', 'whatsapp')

        with transaction.atomic():
            order = Order.objects.create(
                customer_name=validated_data['customer_name'],
                customer_email=validated_data['customer_email'],
                customer_phone=validated_data['customer_phone'],
                deceased_name=validated_data.get('deceased_name', ''),
                delivery_address=validated_data.get('delivery_address', ''),
                delivery_region=validated_data.get('delivery_region', ''),
                delivery_district=validated_data.get('delivery_district', ''),
                delivery_notes=validated_data.get('delivery_notes', ''),
                delivery_date=validated_data.get('delivery_date'),
                payment_method=final_payment_method,
                stripe_payment_intent_id=stripe_payment_intent_id,
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                discount=discount,
                total=total,
                payment_status='pending',
                status='pending',
                payment_currency=payment_currency,
                exchange_rate=exchange_rate,
                total_usd=total_usd,
                language=validated_data.get('language', 'zh-HK'),  # ← new
            )

            for item_data in order_items_data:
                OrderItem.objects.create(order=order, **item_data)

        return order