from django import forms
from django.contrib import admin
from django.db import models

from .models import Product, ProductCategory, ProductImage, ProductOption


class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ["image", "alt_text", "is_primary"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].required = False


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    form = ProductImageForm
    fields = ["image", "alt_text", "is_primary"]


class ProductOptionForm(forms.ModelForm):
    class Meta:
        model = ProductOption
        fields = ["name", "name_en", "price_adjustment", "image", "image_url"]
        widgets = {
            "image_url": forms.URLInput(attrs={"placeholder": "https://example.com/image.jpg"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image_url"].required = False
        self.fields["image"].required = False


class ProductOptionInline(admin.TabularInline):
    model = ProductOption
    extra = 0
    form = ProductOptionForm
    fields = ["name", "name_en", "price_adjustment", "image", "image_url"]


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "name_en", "sort_order", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "name_en")
    ordering = ("sort_order", "id")
    list_editable = ("sort_order",)
    fields = ("name", "name_en", "is_active", "sort_order", "logo", "logo_url")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "price", "is_active", "is_hot_seller", "created_at")
    list_filter = ("is_active", "is_hot_seller", "categories")
    search_fields = ("name",)
    filter_horizontal = ("categories",)
    inlines = (ProductImageInline, ProductOptionInline)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "is_primary", "created_at")
    list_filter = ("is_primary",)


@admin.register(ProductOption)
class ProductOptionAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "name", "name_en", "price_adjustment", "created_at")
    list_filter = ("product",)
    search_fields = ("name", "name_en", "product__name")
