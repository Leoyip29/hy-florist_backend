from django.db import models
from products.models import Product
from utils.models import WithTimeStamps


class Order(WithTimeStamps):
    """
    Represents a customer order in the system.
    Supports guest checkout - no user account required.
    """

    PAYMENT_METHOD_CHOICES = [
        ('stripe', 'Stripe (Credit/Debit Card)'),
        ('apple_pay', 'Apple Pay'),
        ('payme', 'PayMe'),
    ]

    # Order identification
    order_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        help_text="Unique order number generated automatically"
    )

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
    delivery_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Special delivery instructions"
    )

    # Payment information
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='stripe'
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

    def calculate_total(self):
        """Calculate and update order total"""
        self.subtotal = sum(item.line_total for item in self.items.all())
        self.total = self.subtotal + self.delivery_fee - self.discount
        return self.total


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
        """Calculate line total before saving"""
        self.line_total = self.product_price * self.quantity
        super().save(*args, **kwargs)