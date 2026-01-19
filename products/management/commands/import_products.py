import csv
from decimal import Decimal

from django.core.management.base import BaseCommand

from products.models import (
    Product,
    ProductCategory,
    SuitableLocation,
    ProductImage,
)


class Command(BaseCommand):
    help = "Import products from CSV file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to CSV file",
        )

    def handle(self, *args, **options):
        file_path = options["file"]

        with open(file_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                print(row)
                product_name = row["\ufeff產品名稱"].strip()
                category_text = row["分類"]
                location_text = row["適合地點"]
                price_text = row["價格"]
                image_url = row["圖片"]

                # Clean price: "$1,560.00" → Decimal("1560.00")
                price = Decimal(
                    price_text.replace("$", "").replace(",", "").strip()
                )

                # Create or update product
                product, created = Product.objects.get_or_create(
                    name=product_name,
                    defaults={
                        "price": price,
                        "description": "",
                    },
                )

                if not created:
                    product.price = price
                    product.save()

                # Categories (花束多買優惠 / 花束)
                categories = [c.strip() for c in category_text.split("/")]

                for cat_name in categories:
                    category, _ = ProductCategory.objects.get_or_create(
                        name=cat_name
                    )
                    product.categories.add(category)

                # Suitable Locations (教堂 / 殯儀館 / 醫院)
                locations = [l.strip() for l in location_text.split("/")]

                for loc_name in locations:
                    location, _ = SuitableLocation.objects.get_or_create(
                        name=loc_name
                    )
                    product.suitable_locations.add(location)

                # Product Image (URL only)
                ProductImage.objects.get_or_create(
                    product=product,
                    url=image_url,
                    defaults={
                        "is_primary": True,
                        "alt_text": product.name,
                    },
                )

                self.stdout.write(
                    self.style.SUCCESS(f"✔ Imported: {product.name}")
                )

        self.stdout.write(
            self.style.SUCCESS("🎉 All products imported successfully!")
        )
