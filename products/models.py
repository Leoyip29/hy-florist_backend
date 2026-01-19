from django.db import models

from utils.models import WithTimeStamps


# Product Category Model
class ProductCategory(WithTimeStamps):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

# Suitable Location Model
class SuitableLocation(WithTimeStamps):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

# Product Model
class Product(WithTimeStamps):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    # Relationships
    categories = models.ManyToManyField(ProductCategory, related_name='products')
    suitable_locations = models.ManyToManyField(SuitableLocation, related_name='products')

    def __str__(self):
        return self.name

# Product Images Model
class ProductImage(WithTimeStamps):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/',null=True)
    url = models.URLField(max_length=1000,null=True)
    alt_text = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.product.name} Image"
