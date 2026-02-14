from django.db import models
from products.models import Product
from utils.models import WithTimeStamps
from django.utils import timezone


class Order(WithTimeStamps):
    """
    Represents a customer order in the system.
    Supports guest checkout - no user account required.
    """

    PAYMENT_METHOD_CHOICES = [
        ('card_pay', 'Credit/Debit Card'),
        ('apple_pay', 'Apple Pay'),
        ('google_pay', 'Google Pay'),
        ('payme', 'PayMe'),
        ('alipay', 'AliPay'),
    ]

    # Order identification
    order_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        help_text="Unique order number generated automatically"
    )

    STATUS_CHOICES = [
        ('pending', 'Pending Payment'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]

    # Customer information (Guest Checkout)
    customer_name = models.CharField(
        max_length=255,
        help_text="Customer's full name"
    )
    customer_email = models.EmailField(
        help_text="Email for order confirmation"
    )
    customer_phone = models.CharField(
        max_length=20,
        help_text="Contact phone number"
    )

    # Delivery information
    delivery_address = models.TextField(
        help_text="Full delivery address"
    )
    delivery_date = models.DateField(
        help_text="Requested delivery date (must be at least 3 days in advance)",
        null=True
    )
    delivery_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Special delivery instructions"
    )

    # Payment information
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='card_pay'
    )
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('paid', 'Paid'),
            ('failed', 'Failed'),
            ('refunded', 'Refunded'),
        ],
        default='pending'
    )
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Stripe Payment Intent ID for reference"
    )

    # Order status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        help_text="Overall order status"
    )

    # Order totals
    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Subtotal before any fees or discounts"
    )
    delivery_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Delivery/shipping fee"
    )
    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Total discount amount"
    )
    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Final total amount"
    )

    paid_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When payment was completed"
    )
    payment_verified_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When payment was verified with Stripe"
    )
    confirmed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When order was confirmed"
    )

    # Payment currency tracking (NEW)
    payment_currency = models.CharField(
        max_length=3,
        default='HKD',
        help_text="Currency used for payment (HKD or USD)"
    )
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Exchange rate applied (HKD to USD) if payment was in USD"
    )
    total_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total amount in USD (for AliPay payments)"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['order_number']),
            models.Index(fields=['customer_email']),
        ]

    def __str__(self):
        return f"Order #{self.order_number} - {self.customer_name}"

    def save(self, *args, **kwargs):
        """Generate unique order number if not exists"""
        if not self.order_number:
            import uuid
            from datetime import datetime

            # Format: HYF-YYYYMMDD-XXXXX
            date_str = datetime.now().strftime('%Y%m%d')
            unique_id = str(uuid.uuid4().hex[:5]).upper()
            self.order_number = f"HYF-{date_str}-{unique_id}"

        super().save(*args, **kwargs)

    def mark_as_paid(self, payment_intent_id=None):
        """
        Atomically mark order as paid.
        Idempotent - safe to call multiple times.
        """
        if self.payment_status == 'paid':
            return  # Already paid, nothing to do

        if payment_intent_id and not self.stripe_payment_intent_id:
            self.stripe_payment_intent_id = payment_intent_id

        self.payment_status = 'paid'
        self.status = 'processing'
        self.paid_at = timezone.now()
        self.payment_verified_at = timezone.now()
        self.save(update_fields=[
            'payment_status',
            'paid_at',
            'status',
            'payment_verified_at',
            'stripe_payment_intent_id',
            'updated_at'
        ])

    def confirm_order(self):
        """Mark order as confirmed after successful payment"""
        if not self.confirmed_at:
            self.confirmed_at = timezone.now()
            self.save(update_fields=['confirmed_at', 'updated_at'])

    def calculate_total(self):
        """Calculate and update order total"""
        self.subtotal = sum(item.line_total for item in self.items.all())
        self.total = self.subtotal + self.delivery_fee - self.discount
        return self.total

    def get_payment_method_display_name(self):
        """Return a user-friendly display name for the payment method"""
        payment_method_names = {
            'card_pay': '信用卡 / 扣賬卡',
            'apple_pay': 'Apple Pay',
            'google_pay': 'Google Pay',
            'payme': 'PayMe',
            'alipay': 'AliPay',  # Added AliPay
        }
        return payment_method_names.get(self.payment_method, self.payment_method)


class OrderItem(WithTimeStamps):
    """
    Represents an individual item within an order.
    Stores product details at the time of order to preserve historical data.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        help_text="The order this item belongs to"
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        help_text="The product being ordered"
    )

    # Quantity and pricing
    quantity = models.PositiveIntegerField(
        default=1,
        help_text="Number of items ordered"
    )
    product_name = models.CharField(
        max_length=255,
        help_text="Product name at time of order",
        null=True
    )
    product_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        help_text="Product price at time of order"
    )
    line_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total for this line (quantity × price)"
    )

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        ordering = ['id']

    def __str__(self):
        return f"{self.quantity}x {self.product_name} (Order #{self.order.order_number})"

    def save(self, *args, **kwargs):
        if not self.line_total or self.line_total == 0:
            self.line_total = self.product_price * self.quantity
        super().save(*args, **kwargs)


class StripeWebhookEvent(models.Model):
    """
    Records every Stripe webhook event that has been successfully processed.
    Prevents duplicate processing when Stripe retries delivery.
    """
    event_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Stripe event ID (e.g. evt_1xxxxx)"
    )
    event_type = models.CharField(
        max_length=100,
        help_text="Stripe event type (e.g. payment_intent.succeeded)"
    )
    processed_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this event was first processed"
    )

    class Meta:
        verbose_name = "Stripe Webhook Event"
        verbose_name_plural = "Stripe Webhook Events"
        indexes = [
            models.Index(fields=['event_id']),
            models.Index(fields=['-processed_at']),
        ]

    def __str__(self):
        return f"{self.event_type} — {self.event_id}"