from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0008_populate_name_en"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="product",
            name="suitable_locations",
        ),
        migrations.DeleteModel(
            name="SuitableLocation",
        ),
    ]
