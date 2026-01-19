from rest_framework import serializers
from products.models import Product, ProductCategory, SuitableLocation, ProductImage


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "name"]


class SuitableLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuitableLocation
        fields = ["id", "name"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "url", "alt_text", "is_primary"]


class ProductListSerializer(serializers.ModelSerializer):
    categories = ProductCategorySerializer(many=True)
    suitable_locations = SuitableLocationSerializer(many=True)
    images = ProductImageSerializer(many=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "price",
            "categories",
            "suitable_locations",
            "images",
        ]
