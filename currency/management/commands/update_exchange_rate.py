"""
Django management command to manually update exchange rate

Usage:
    python manage.py update_exchange_rate
    python manage.py update_exchange_rate --show-info
    python manage.py update_exchange_rate --history 7
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from utils.currency_service import update_exchange_rate, get_rate_info, get_rate_history
from currency.models import CurrencyRate
from decimal import Decimal


class Command(BaseCommand):
    help = 'Manually update exchange rate from ExchangeRate-API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--show-info',
            action='store_true',
            help='Show current rate information without updating',
        )
        parser.add_argument(
            '--history',
            type=int,
            default=0,
            help='Show rate history for specified number of days',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.HTTP_INFO('=' * 70))
        self.stdout.write(self.style.HTTP_INFO('Exchange Rate Management'))
        self.stdout.write(self.style.HTTP_INFO('=' * 70))

        if options['show_info']:
            self.show_current_info()
        elif options['history'] > 0:
            self.show_history(options['history'])
        else:
            self.update_rate()

    def show_current_info(self):
        """Display current exchange rate information"""
        self.stdout.write('\n📊 Current Exchange Rate Information\n')

        rate_info = get_rate_info()

        if rate_info.get('rate'):
            self.stdout.write(
                self.style.SUCCESS(
                    f'Rate: 1 USD = {rate_info["rate"]} HKD'
                )
            )
            self.stdout.write(f'Created: {rate_info["created_at"]}')
            self.stdout.write(f'Updated: {rate_info["updated_at"]}')
            self.stdout.write(f'Age: {rate_info["age_hours"]:.1f} hours')

            if rate_info['is_fresh']:
                self.stdout.write(
                    self.style.SUCCESS('✓ Rate is fresh (less than 24 hours old)')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠ Rate is {rate_info["age_hours"]:.1f} hours old')
                )

            # Show next update time
            from datetime import timedelta
            next_update = rate_info['created_at'].replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            next_update = next_update + timedelta(days=1)

            self.stdout.write(f'\nNext Scheduled Update: {next_update} (midnight)')

        else:
            self.stdout.write(
                self.style.ERROR('✗ No exchange rate found in database!')
            )
            self.stdout.write('  Run: python manage.py update_exchange_rate')

    def show_history(self, days):
        """Show historical exchange rates"""
        self.stdout.write(f'\n📈 Exchange Rate History (Last {days} Days)\n')

        history = get_rate_history(days=days)

        if not history:
            self.stdout.write(
                self.style.WARNING('No historical data available')
            )
            return

        # Display in table format
        self.stdout.write(
            f'{"Date":<12} {"Time":<8} {"Rate (USD → HKD)":<20}'
        )
        self.stdout.write('-' * 40)

        for record in history:
            date_str = record.created_at.strftime('%Y-%m-%d')
            time_str = record.created_at.strftime('%H:%M')
            rate_str = f'{record.rate}'

            self.stdout.write(
                f'{date_str:<12} {time_str:<8} {rate_str:<20}'
            )

        # Show statistics
        rates = [Decimal(str(r.rate)) for r in history]
        if rates:
            avg_rate = sum(rates) / len(rates)
            min_rate = min(rates)
            max_rate = max(rates)

            self.stdout.write('\n' + '=' * 70)
            self.stdout.write('Statistics:')
            self.stdout.write(f'  Records: {len(rates)}')
            self.stdout.write(f'  Average: {avg_rate:.6f} HKD')
            self.stdout.write(f'  Minimum: {min_rate:.6f} HKD')
            self.stdout.write(f'  Maximum: {max_rate:.6f} HKD')
            self.stdout.write(f'  Range:   {max_rate - min_rate:.6f} HKD')

            # Show trend
            if len(rates) >= 2:
                first_rate = rates[0]
                last_rate = rates[-1]
                change = last_rate - first_rate
                change_percent = (change / first_rate) * 100

                if change > 0:
                    trend = self.style.SUCCESS(f'↗ Increasing')
                elif change < 0:
                    trend = self.style.WARNING(f'↘ Decreasing')
                else:
                    trend = '→ Stable'

                self.stdout.write(f'  Trend:   {trend} ({change_percent:+.4f}%)')

    def update_rate(self):
        """Fetch and update exchange rate"""
        self.stdout.write('\n🔄 Updating Exchange Rate...\n')

        try:
            success, rate, message = update_exchange_rate()

            if success:
                self.stdout.write(
                    self.style.SUCCESS(f'✓ {message}')
                )
                self.stdout.write(f'  Rate: 1 USD = {rate} HKD')

                # Show test conversion
                test_hkd = Decimal('780.00')
                test_usd = test_hkd / rate
                self.stdout.write(
                    f'\n💱 Test Conversion: HKD ${test_hkd} = USD ${test_usd:.2f}'
                )

            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠ {message}')
                )
                if rate:
                    self.stdout.write(f'  Using rate: 1 USD = {rate} HKD')

            # Show database stats
            total_records = CurrencyRate.objects.filter(
                base_currency='USD',
                target_currency='HKD'
            ).count()
            self.stdout.write(f'\nTotal USD→HKD records in database: {total_records}')

            # Show oldest and newest
            oldest = CurrencyRate.objects.filter(
                base_currency='USD',
                target_currency='HKD'
            ).order_by('created_at').first()

            if oldest:
                age_days = (timezone.now() - oldest.created_at).days
                self.stdout.write(f'Oldest record: {oldest.created_at.strftime("%Y-%m-%d")} ({age_days} days ago)')

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Error: {str(e)}')
            )

        self.stdout.write('')