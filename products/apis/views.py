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


class ProductByIdsAPIView(ListAPIView):
    """
    API endpoint to fetch products by specific IDs.
    Usage: /apis/products/by-ids/?ids=1,2,3,4,5,6
    """
    serializer_class = ProductListSerializer

    def get_queryset(self):
        ids_param = self.request.query_params.get('ids', '')
        if not ids_param:
            return Product.objects.none()
        
        # Convert comma-separated string to list of integers
        try:
            ids_list = [int(id.strip()) for id in ids_param.split(',') if id.strip().isdigit()]
            return Product.objects.filter(id__in=ids_list).order_by('id')
        except ValueError:
            return Product.objects.none()