from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0012_order_language_alter_order_payment_method_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='order',
            old_name='total_usd',
            new_name='total_cny',
        ),
    ]