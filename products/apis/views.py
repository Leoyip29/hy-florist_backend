from decimal import Decimal

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
        queryset = Product.objects.filter(is_active=True).prefetch_related(
            'categories',
            'images',
            'options',
        )

        # Get filter parameters
        category = self.request.query_params.get('category', None)
        search = self.request.query_params.get('search', None)
        sort = self.request.query_params.get('sort', None)
        price_min = self.request.query_params.get('price_min', None)
        price_max = self.request.query_params.get('price_max', None)

        # Filter by price range
        if price_min:
            try:
                queryset = queryset.filter(price__gte=Decimal(price_min))
            except Exception:
                pass
        if price_max:
            try:
                queryset = queryset.filter(price__lte=Decimal(price_max))
            except Exception:
                pass

        # Filter by category (supports both English name_en and Chinese name)
        if category and category.lower() != 'all' and category != '全部':
            from products.models import ProductCategory
            cats = ProductCategory.objects.filter(name_en=category, is_active=True)
            if not cats.exists():
                cats = ProductCategory.objects.filter(name=category, is_active=True)
            if not cats.exists():
                cats = ProductCategory.objects.filter(name__iexact=category, is_active=True)
            if cats.exists():
                queryset = queryset.filter(categories__in=cats).distinct()

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
            return Product.objects.filter(id__in=ids_list).prefetch_related(
                'categories',
                'images',
                'options',
            ).order_by('id')
        except ValueError:
            return Product.objects.none()


class CategoryListAPIView(ListAPIView):
    """
    API endpoint to get all categories.
    Returns: { categories: [...] }
    """
    serializer_class = ProductListSerializer  # placeholder, not used directly

    def list(self, request, *args, **kwargs):
        from products.models import ProductCategory
        from .serializers import ProductCategorySerializer

        categories = ProductCategory.objects.filter(is_active=True).order_by('sort_order', 'id')
        serializer = ProductCategorySerializer(categories, many=True, context={"request": request})
        return Response({
            'categories': serializer.data,
        })


# Price ranges matching the frontend PRICE_RANGES in product-utils.ts
_PRICE_RANGES = [
    {"key": "400to600", "min": 400, "max": 600},
    {"key": "600to800", "min": 600, "max": 800},
    {"key": "800to1000", "min": 800, "max": 1000},
    {"key": "1000to1500", "min": 1000, "max": 1500},
    {"key": "1500to2000", "min": 1500, "max": 2000},
    {"key": "2000to3000", "min": 2000, "max": 3000},
    {"key": "over3000", "min": 3000, "max": None},
]


class CategoryPriceRangesAPIView(ListAPIView):
    """
    Returns which price range keys have products for the given category.
    Usage: /apis/products/price-ranges/?category=Rose
    Returns: { available_ranges: ["400to600", "600to800", ...] }
    """

    def list(self, request, *args, **kwargs):
        from products.models import ProductCategory

        category = request.query_params.get("category", None)
        queryset = Product.objects.filter(is_active=True)

        if category and category.lower() != "all" and category != "全部":
            cats = ProductCategory.objects.filter(name_en=category, is_active=True)
            if not cats.exists():
                cats = ProductCategory.objects.filter(name=category, is_active=True)
            if not cats.exists():
                cats = ProductCategory.objects.filter(name__iexact=category, is_active=True)
            if cats.exists():
                queryset = queryset.filter(categories__in=cats).distinct()

        prices = list(queryset.values_list("price", flat=True))

        available_ranges = []
        for pr in _PRICE_RANGES:
            if pr["key"] == "over3000":
                has_products = any(p >= pr["min"] for p in prices)
            else:
                has_products = any(pr["min"] <= p <= pr["max"] for p in prices)
            if has_products:
                available_ranges.append(pr["key"])

        return Response({"available_ranges": available_ranges})