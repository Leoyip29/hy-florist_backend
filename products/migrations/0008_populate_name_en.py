from django.db import migrations


CATEGORY_NAMES = {
    "全部": "All",
    "花束": "Bouquets",
    "花籃": "Flower Baskets",
    "花束多買優惠": "Bouquet Bundle Offers",
    "花牌": "Funeral Flower Boards",
    "心型花牌": "Heart-shaped Boards",
    "十字架花牌": "Cross Boards",
    "圓型花牌": "Round Boards",
    "棺面花": "Casket Decorations",
    "場地裝飾": "Venue Decorations",
    "台花": "Stand Flowers",
    "講台花": "Podium Flowers",
    "櫈花": "Bench Flowers",
    "場地系列": "Venue Series",
    "花牌套餐": "Board Sets",
}


def update_category_names(apps, schema_editor):
    ProductCategory = apps.get_model("products", "ProductCategory")
    for cat in ProductCategory.objects.all():
        if cat.name in CATEGORY_NAMES:
            cat.name_en = CATEGORY_NAMES[cat.name]
            cat.save(update_fields=["name_en"])


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0007_add_category_logo_fields"),
    ]

    operations = [
        migrations.RunPython(update_category_names, reverse),
    ]
