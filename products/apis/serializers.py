from rest_framework import serializers
from django.conf import settings
from products.models import Product, ProductCategory, ProductImage, ProductOption


def _media_url(path: str | None, context: dict | None = None) -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base = settings.API_BASE_URL
    if not base or base == "http://localhost:8000":
        req = context.get("request") if context else None
        if req:
            forwarded_host = req.META.get("HTTP_X_FORWARDED_HOST", "")
            host = forwarded_host.strip()
            # Strip scheme if present (some proxies send it in X-Forwarded-Host)
            if host.startswith("http://"):
                host = host[7:]
            elif host.startswith("https://"):
                host = host[8:]
            # Strip trailing slash
            host = host.rstrip("/")
            if not host:
                host = req.get_host()
            proto = req.META.get("HTTP_X_FORWARDED_PROTO", "https" if req.is_secure() else "http")
            base = f"{proto}://{host}"
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
        fields = ["id", "name", "name_en", "logo", "logo_url"]

    def get_logo(self, obj: "ProductCategory") -> str | None:
        return _media_url(obj.logo_url, self.context) or _media_url(obj.logo.name if obj.logo else None, self.context)


class ProductImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ["id", "image", "alt_text", "is_primary"]

    def get_image(self, obj: "ProductImage") -> str | None:
        return _media_url(obj.image.name if obj.image else None, self.context)


class ProductListSerializer(serializers.ModelSerializer):
    categories = ProductCategorySerializer(many=True)
    images = ProductImageSerializer(many=True)
    options = ProductOptionSerializer(many=True)

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
