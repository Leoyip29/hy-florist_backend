from django.urls import path
from products.apis.views import ProductListAPIView

urlpatterns = [
    path("products/", ProductListAPIView.as_view(), name="product-list"),
]
