from django.db import models
from django.conf import settings

from utils.models import WithTimeStamps


# Product Category Model
class ProductCategory(WithTimeStamps):
    name = models.CharField(max_length=100, unique=True)
    name_en = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    logo = models.ImageField(upload_to='categories/', null=True, blank=True)
    logo_url = models.URLField(max_length=1000, null=True, blank=True)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name

# Product Model
class Product(WithTimeStamps):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    # Hot seller flag - shows products at top when sorting by hot selling
    is_hot_seller = models.BooleanField(default=False)

    # Active flag - can be disabled from admin
    is_active = models.BooleanField(default=True)

    # Relationships
    categories = models.ManyToManyField(ProductCategory, related_name='products')

    def __str__(self):
        return self.name

# Product Images Model
class ProductImage(WithTimeStamps):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/', null=True)
    alt_text = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.product.name} Image"


# Product Option Model - for products with selectable options (like board types)
class ProductOption(WithTimeStamps):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='options')
    name = models.CharField(max_length=100)  # e.g., "十字架", "圓型", "心型"
    name_en = models.CharField(max_length=100)  # e.g., "Cross", "Round", "Heart-shaped"
    # Optional price adjustment - some options might cost more
    price_adjustment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Optional image for this specific option
    image = models.ImageField(upload_to='products/options/', null=True, blank=True)
    image_url = models.URLField(max_length=1000, null=True, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.product.name} - {self.name}"
