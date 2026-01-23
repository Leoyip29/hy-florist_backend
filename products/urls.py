from django.urls import path
from products.apis.views import ProductListAPIView, ProductByIdsAPIView

urlpatterns = [
    path("products/", ProductListAPIView.as_view(), name="product-list"),
    path("products/by-ids/", ProductByIdsAPIView.as_view(), name="product-by-ids"),
]
