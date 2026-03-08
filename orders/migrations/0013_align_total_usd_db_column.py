from django.db import migrations, models


class Migration(migrations.Migration):
    """
    The actual DB column is named 'total_cny' (not 'total_usd').
    This migration updates Django's state to reflect that via db_column='total_cny',
    without executing any SQL (the column already exists with the correct name).
    """

    dependencies = [
        ('orders', '0012_order_language_alter_order_payment_method_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='order',
                    name='total_usd',
                    field=models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        db_column='total_cny',
                        help_text='Unused, kept for backwards compatibility',
                        max_digits=10,
                        null=True,
                    ),
                ),
            ],
            database_operations=[],  # column already exists as 'total_cny' in DB
        ),
    ]