from django.contrib import admin
from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    """Inline admin for order items"""
    model = OrderItem
    extra = 0
    readonly_fields = ['product_name', 'product_price', 'quantity', 'line_total']
    fields = ['product', 'product_name', 'quantity', 'product_price', 'line_total']
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Admin interface for Order model"""

    list_display = [
        'order_number',
        'customer_name',
        'customer_email',
        'total',
        'payment_status',
        'delivery_date',
        'created_at',
    ]

    list_filter = [
        'payment_status',
        'payment_method',
        'created_at',
    ]

    search_fields = [
        'order_number',
        'customer_name',
        'customer_email',
        'customer_phone',
    ]

    readonly_fields = [
        'order_number',
        'created_at',
        'updated_at',
        'paid_at',
        'stripe_payment_intent_id',
        'subtotal',
        'total',
    ]

    fieldsets = (
        ('Order Information', {
            'fields': (
                'order_number',
                'created_at',
                'updated_at',
            )
        }),
        ('Customer Information', {
            'fields': (
                'customer_name',
                'customer_email',
                'customer_phone',
            )
        }),
        ('Delivery Information', {
            'fields': (
                'delivery_address',
                'delivery_notes',
            )
        }),
        ('Payment Information', {
            'fields': (
                'payment_method',
                'payment_status',
                'stripe_payment_intent_id',
                'paid_at',
            )
        }),
        ('Order Totals', {
            'fields': (
                'subtotal',
                'delivery_fee',
                'discount',
                'total',
            )
        }),
    )

    inlines = [OrderItemInline]

    def has_add_permission(self, request):
        """Prevent manual order creation through admin"""
        return False


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    """Admin interface for OrderItem model"""

    list_display = [
        'order',
        'product_name',
        'quantity',
        'product_price',
        'line_total',
    ]

    list_filter = [ 'created_at']

    search_fields = [
        'order__order_number',
        'product_name',
    ]

    readonly_fields = [
        'order',
        'product',
        'product_name',
        'product_price',
        'quantity',
        'line_total',
        'created_at',
        'updated_at',
    ]

    def has_add_permission(self, request):
        """Prevent manual creation through admin"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion through admin"""
        return False