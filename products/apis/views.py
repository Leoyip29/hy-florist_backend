from rest_framework.generics import ListAPIView
from products.models import Product
from .serializers import ProductListSerializer


class ProductListAPIView(ListAPIView):
    serializer_class = ProductListSerializer

    def get_queryset(self):
        return (
            Product.objects.all()
            .order_by("-created_at")
        )
