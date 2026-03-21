from django.db import migrations


class Migration(migrations.Migration):
    """
    Migration 0013 assumed the DB column was already named 'total_cny' (from a
    manual rename on the old production DB) and skipped the actual SQL rename.
    On a fresh database install, migration 0011 creates the column as 'total_usd'
    and 0013 never renames it, causing a ProgrammingError because the model
    declares db_column='total_cny'.

    This migration performs the actual column rename so fresh installs work correctly.
    """

    dependencies = [
        ('orders', '0014_alter_order_exchange_rate_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='orders_order' AND column_name='total_usd'
                    ) THEN
                        ALTER TABLE orders_order RENAME COLUMN total_usd TO total_cny;
                    END IF;
                END $$;
            """,
            reverse_sql="""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='orders_order' AND column_name='total_cny'
                    ) THEN
                        ALTER TABLE orders_order RENAME COLUMN total_cny TO total_usd;
                    END IF;
                END $$;
            """,
        ),
    ]
