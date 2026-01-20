from django.contrib import admin

from .models import Product, ProductCategory, SuitableLocation, ProductImage


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(SuitableLocation)
class SuitableLocationAdmin(admin.ModelAdmin):
    search_fields = ("name",)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "price", "created_at")
    search_fields = ("name",)
    filter_horizontal = ("categories", "suitable_locations")
    inlines = (ProductImageInline,)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "is_primary", "created_at")
    list_filter = ("is_primary",)
