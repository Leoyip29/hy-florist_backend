from django import forms
from django.contrib import admin

from .models import Product, ProductCategory, SuitableLocation, ProductImage


class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ["url", "image", "alt_text", "is_primary"]
        widgets = {
            "url": forms.URLInput(attrs={"placeholder": "https://example.com/image.jpg"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make both URL and image fields optional
        self.fields["url"].required = False
        self.fields["image"].required = False


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    form = ProductImageForm
    fields = ["url", "image", "alt_text", "is_primary"]


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(SuitableLocation)
class SuitableLocationAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "price", "is_hot_seller", "created_at")
    search_fields = ("name",)
    filter_horizontal = ("categories", "suitable_locations")
    inlines = (ProductImageInline,)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "is_primary", "created_at")
    list_filter = ("is_primary",)
