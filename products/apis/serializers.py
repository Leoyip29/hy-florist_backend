from rest_framework import serializers
from django.conf import settings
from products.models import Product, ProductCategory, ProductImage, ProductOption


def _media_url(path: str | None, context: dict | None = None) -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base = settings.API_BASE_URL.rstrip("/")
    return f"{base}/media/{path.lstrip('/')}"


class ProductOptionSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = ProductOption
        fields = ["id", "name", "name_en", "price_adjustment", "image", "image_url"]

    def get_image(self, obj: "ProductOption") -> str | None:
        return _media_url(obj.image_url, self.context) or _media_url(obj.image.name if obj.image else None, self.context)


class ProductCategorySerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()

    class Meta:
        model = ProductCategory
        fields = ["id", "name", "name_en", "logo"]

    def get_logo(self, obj: "ProductCategory") -> str | None:
        return _media_url(obj.logo.name if obj.logo else None, self.context)


class ProductImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ["id", "image", "alt_text", "is_primary"]

    def get_image(self, obj: "ProductImage") -> str | None:
        return _media_url(obj.image.name if obj.image else None, self.context)


# ── Child serializers must be defined BEFORE ProductListSerializer ──
# to avoid circular-import issues. They reference self.context
# (passed explicitly via SerializerMethodField in ProductListSerializer).


class ProductListSerializer(serializers.ModelSerializer):
    categories = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "price",
            "is_hot_seller",
            "categories",
            "images",
            "options",
        ]

    def get_categories(self, obj):
        cats = getattr(obj, "categories", []).all() if hasattr(obj, "categories") else []
        return ProductCategorySerializer(cats, many=True, context=self.context).data

    def get_images(self, obj):
        imgs = getattr(obj, "images", []).all() if hasattr(obj, "images") else []
        return ProductImageSerializer(imgs, many=True, context=self.context).data

    def get_options(self, obj):
        opts = getattr(obj, "options", []).all() if hasattr(obj, "options") else []
        return ProductOptionSerializer(opts, many=True, context=self.context).data
