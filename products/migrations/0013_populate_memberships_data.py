# Data migration to populate ProductCategoryMembership records for existing M2M relationships
from django.db import migrations


def populate_memberships(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    ProductCategoryMembership = apps.get_model('products', 'ProductCategoryMembership')

    created_count = 0
    for product in Product.objects.filter(is_active=True).prefetch_related('categories'):
        for category in product.categories.all():
            membership, created = ProductCategoryMembership.objects.get_or_create(
                product=product,
                category=category,
                defaults={'display_order': 0}
            )
            if created:
                created_count += 1

    print(f"Created {created_count} ProductCategoryMembership records")


def reverse_migration(apps, schema_editor):
    # No need to clean up on reverse - just leave orphan records
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('products', '0012_add_product_category_membership'),
    ]

    operations = [
        migrations.RunPython(populate_memberships, reverse_migration),
    ]
