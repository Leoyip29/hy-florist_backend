import csv
import os
import requests
from decimal import Decimal
from urllib.parse import urlparse
from io import BytesIO

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile

from products.models import (
    Product,
    ProductCategory,
    SuitableLocation,
    ProductImage,
)


class Command(BaseCommand):
    help = "Import products from CSV file and download images locally"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to CSV file",
        )
        parser.add_argument(
            "--skip-images",
            action="store_true",
            help="Skip downloading images (use URL only)",
        )

    def download_image(self, url, product_name):
        """
        Download image from URL and return a Django File object
        """
        try:
            self.stdout.write(f"  📥 Downloading image from: {url}")

            # Set headers to mimic a browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # Get filename from URL
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path)

            # If no filename in URL, generate one
            if not filename or '.' not in filename:
                # Try to get extension from Content-Type
                content_type = response.headers.get('content-type', '')
                ext = 'jpg'  # default
                if 'png' in content_type:
                    ext = 'png'
                elif 'webp' in content_type:
                    ext = 'webp'
                elif 'gif' in content_type:
                    ext = 'gif'

                # Create filename from product name
                safe_name = "".join(c for c in product_name if c.isalnum() or c in (' ', '-', '_')).strip()
                safe_name = safe_name.replace(' ', '_')[:50]  # Limit length
                filename = f"{safe_name}.{ext}"

            # Create Django File object
            image_content = ContentFile(response.content)
            image_content.name = filename

            self.stdout.write(self.style.SUCCESS(f"  ✔ Downloaded: {filename}"))
            return image_content

        except requests.exceptions.RequestException as e:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ Failed to download image: {str(e)}")
            )
            return None
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ Error processing image: {str(e)}")
            )
            return None

    def handle(self, *args, **options):
        file_path = options["file"]
        skip_images = options.get("skip_images", False)

        if not os.path.exists(file_path):
            self.stdout.write(
                self.style.ERROR(f"❌ File not found: {file_path}")
            )
            return

        with open(file_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            total_products = 0
            successful_imports = 0
            failed_imports = 0

            for row in reader:
                total_products += 1
                try:
                    # Handle BOM in first column if present
                    first_key = list(row.keys())[0]
                    product_name = row[first_key].strip()

                    category_text = row["分類"]
                    location_text = row["適合地點"]
                    price_text = row["價格"]
                    image_url = row["圖片"]

                    self.stdout.write(f"\n{'=' * 60}")
                    self.stdout.write(f"Processing: {product_name}")
                    self.stdout.write(f"{'=' * 60}")

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
                        self.stdout.write("  ℹ Product already exists, updating price")
                    else:
                        self.stdout.write(self.style.SUCCESS("  ✔ Created new product"))

                    # Categories (花束多買優惠 / 花束)
                    categories = [c.strip() for c in category_text.split("/")]
                    product.categories.clear()  # Clear existing to avoid duplicates

                    for cat_name in categories:
                        category, _ = ProductCategory.objects.get_or_create(
                            name=cat_name
                        )
                        product.categories.add(category)
                        self.stdout.write(f"  📁 Added category: {cat_name}")

                    # Suitable Locations (教堂 / 殯儀館 / 醫院)
                    locations = [l.strip() for l in location_text.split("/")]
                    product.suitable_locations.clear()  # Clear existing to avoid duplicates

                    for loc_name in locations:
                        location, _ = SuitableLocation.objects.get_or_create(
                            name=loc_name
                        )
                        product.suitable_locations.add(location)
                        self.stdout.write(f"  📍 Added location: {loc_name}")

                    # Handle Product Image
                    if image_url:
                        # Check if image already exists for this product
                        existing_image = ProductImage.objects.filter(
                            product=product,
                            url=image_url
                        ).first()

                        if existing_image:
                            self.stdout.write("  ℹ Image already exists for this product")
                        else:
                            if skip_images:
                                # Store URL only
                                ProductImage.objects.create(
                                    product=product,
                                    url=image_url,
                                    is_primary=True,
                                    alt_text=product.name,
                                )
                                self.stdout.write("  🔗 Stored image URL")
                            else:
                                # Download and store image locally
                                image_file = self.download_image(image_url, product_name)

                                if image_file:
                                    ProductImage.objects.create(
                                        product=product,
                                        image=image_file,
                                        url=image_url,  # Keep URL as reference
                                        is_primary=True,
                                        alt_text=product.name,
                                    )
                                    self.stdout.write(self.style.SUCCESS("  ✔ Saved image locally"))
                                else:
                                    # Fallback to URL only if download fails
                                    ProductImage.objects.create(
                                        product=product,
                                        url=image_url,
                                        is_primary=True,
                                        alt_text=product.name,
                                    )
                                    self.stdout.write("  ⚠ Stored URL only (download failed)")

                    successful_imports += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"✔ Successfully imported: {product.name}")
                    )

                except Exception as e:
                    failed_imports += 1
                    self.stdout.write(
                        self.style.ERROR(f"❌ Error importing {product_name}: {str(e)}")
                    )
                    continue

        # Summary
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(self.style.SUCCESS("🎉 IMPORT SUMMARY"))
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"Total products processed: {total_products}")
        self.stdout.write(self.style.SUCCESS(f"✔ Successful: {successful_imports}"))
        if failed_imports > 0:
            self.stdout.write(self.style.ERROR(f"❌ Failed: {failed_imports}"))
        self.stdout.write(f"{'=' * 60}\n")