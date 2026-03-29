from django.urls import path
from products.apis.views import (
    ProductListAPIView,
    ProductByIdsAPIView,
    CategoryListAPIView,
    CategoryPriceRangesAPIView,
)

urlpatterns = [
    path("products/", ProductListAPIView.as_view(), name="product-list"),
    path("products/by-ids/", ProductByIdsAPIView.as_view(), name="product-by-ids"),
    path("products/price-ranges/", CategoryPriceRangesAPIView.as_view(), name="product-price-ranges"),
    path("categories/", CategoryListAPIView.as_view(), name="category-list"),
]
