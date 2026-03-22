from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from django.db import models
from django.db.models import F, Value, FloatField
from products.models import Product
from .serializers import ProductListSerializer


class ProductPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 50


class ProductListAPIView(ListAPIView):
    serializer_class = ProductListSerializer
    pagination_class = ProductPagination

    def get_queryset(self):
        queryset = Product.objects.filter(is_active=True)

        # Get filter parameters
        category = self.request.query_params.get('category', None)
        location = self.request.query_params.get('location', None)
        search = self.request.query_params.get('search', None)
        sort = self.request.query_params.get('sort', None)

        # Filter by category (supports both Chinese and English category names)
        if category and category.lower() != 'all' and category != '全部':
            from products.models import ProductCategory
            cats = ProductCategory.objects.filter(name=category, is_active=True)
            if not cats.exists():
                cats = ProductCategory.objects.filter(name__iexact=category, is_active=True)
            if cats.exists():
                queryset = queryset.filter(categories__in=cats).distinct()

        # Filter by suitable location
        if location and location.lower() != 'all' and location != '全部':
            from products.models import SuitableLocation
            locs = SuitableLocation.objects.filter(name=location)
            if not locs.exists():
                locs = SuitableLocation.objects.filter(name__iexact=location)
            if locs.exists():
                queryset = queryset.filter(suitable_locations__in=locs).distinct()

        # Search by name or description
        if search:
            queryset = queryset.filter(
                models.Q(name__icontains=search) |
                models.Q(description__icontains=search)
            )

        # Apply sorting
        if sort == 'hot':
            return queryset.filter(is_hot_seller=True).order_by('-created_at')

        if sort == 'price_asc':
            return queryset.order_by('price')

        if sort == 'price_desc':
            return queryset.order_by('-price')

        # Default: medium price first, then cheapest to highest
        # Calculate median price from the queryset
        # Get all prices from the filtered queryset
        prices = list(queryset.values_list('price', flat=True))

        if prices:
            # Calculate median
            sorted_prices = sorted(prices)
            n = len(sorted_prices)
            if n % 2 == 0:
                median_price = (sorted_prices[n // 2 - 1] + sorted_prices[n // 2]) / 2
            else:
                median_price = sorted_prices[n // 2]

            # Order by: closest to median first, then by price ascending
            from django.db.models.functions import Abs, Cast

            # Cast price to float for proper distance calculation
            queryset = queryset.annotate(
                distance_from_median=Abs(Cast(F('price'), output_field=FloatField()) - Value(float(median_price)))
            ).order_by('distance_from_median', 'price', 'id')

        return queryset


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


class CategoryListAPIView(ListAPIView):
    """
    API endpoint to get all categories and locations.
    Returns: { categories: [...], locations: [...] }
    """

    def list(self, request, *args, **kwargs):
        from products.models import ProductCategory, SuitableLocation

        categories = list(ProductCategory.objects.filter(is_active=True).values_list('name', flat=True))
        locations = list(SuitableLocation.objects.values_list('name', flat=True))

        return Response({
            'categories': categories,
            'locations': locations
        })