"""
Database-based Currency Service for HY Florist
Fetches rates from ExchangeRate-API and stores in CurrencyRate model
"""
from decimal import Decimal
import requests
import logging
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Fallback exchange rate if database is empty AND API fails
FALLBACK_RATE = Decimal('7.80')


def fetch_exchange_rate_from_api():
    """
    Fetch current USD to HKD exchange rate from ExchangeRate-API.

    Returns:
        Decimal: Exchange rate (1 USD = X HKD) or None if failed
    """
    try:
        api_key = getattr(settings, 'EXCHANGERATE_API_KEY', None)

        if api_key:
            # Paid tier with API key
            url = f'https://v6.exchangerate-api.com/v6/{api_key}/latest/USD'
        else:
            # Free tier (no API key required)
            url = 'https://open.er-api.com/v6/latest/USD'

        logger.info(f"Fetching exchange rate from ExchangeRate-API...")

        response = requests.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()

        if data.get('result') == 'success':
            hkd_rate = Decimal(str(data['conversion_rates']['HKD']))

            # Validate rate is reasonable (HKD typically 7.75 - 7.85)
            if Decimal('7.50') <= hkd_rate <= Decimal('8.50'):
                logger.info(f"Successfully fetched rate: 1 USD = {hkd_rate} HKD")
                return hkd_rate
            else:
                logger.error(
                    f"Rate {hkd_rate} outside expected range (7.50-8.50), rejecting"
                )
                return None
        else:
            logger.error(f"API returned error: {data.get('error-type')}")
            return None

    except requests.exceptions.Timeout:
        logger.error("API request timed out after 10 seconds")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching exchange rate: {e}")
        return None
    except (KeyError, ValueError, TypeError) as e:
        logger.error(f"Error parsing API response: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching exchange rate: {e}", exc_info=True)
        return None


def update_exchange_rate():
    """
    Fetch latest exchange rate from API and save to database.
    Called by scheduled task (midnight cron job).

    Returns:
        tuple: (success: bool, rate: Decimal or None, message: str)
    """
    from currency.models import CurrencyRate

    try:
        # Fetch from API
        rate = fetch_exchange_rate_from_api()

        if rate is None:
            # API failed - check if we have recent rate in database
            latest = get_latest_rate()

            if latest:
                message = (
                    f"API fetch failed, but database has recent rate: {latest} HKD. "
                    "No new rate stored."
                )
                logger.warning(message)
                return False, latest, message
            else:
                # No rate in database either - store fallback
                CurrencyRate.objects.create(
                    base_currency='USD',
                    target_currency='HKD',
                    rate=FALLBACK_RATE
                )
                message = (
                    f"API failed and no database rate exists. "
                    f"Stored fallback rate: {FALLBACK_RATE} HKD"
                )
                logger.error(message)

                # Send alert
                send_exchange_rate_alert(message)

                return False, FALLBACK_RATE, message

        # API succeeded - save to database
        currency_rate = CurrencyRate.objects.create(
            base_currency='USD',
            target_currency='HKD',
            rate=rate
        )

        message = f"Successfully updated exchange rate: 1 USD = {rate} HKD"
        logger.info(message)

        # Cleanup old rates (keep last 90 days)
        deleted_count = cleanup_old_rates(days_to_keep=90)
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old exchange rate records")

        return True, rate, message

    except Exception as e:
        message = f"Error updating exchange rate: {str(e)}"
        logger.error(message, exc_info=True)

        # Try to get existing rate from database as fallback
        latest = get_latest_rate()

        if latest:
            return False, latest, f"{message}. Using existing database rate: {latest}"
        else:
            return False, FALLBACK_RATE, f"{message}. Using fallback: {FALLBACK_RATE}"


def get_latest_rate(base_currency='USD', target_currency='HKD'):
    """
    Get the most recent exchange rate for a currency pair from database.

    Args:
        base_currency: Source currency code (default: USD)
        target_currency: Target currency code (default: HKD)

    Returns:
        Decimal: Exchange rate or None if not found
    """
    from currency.models import CurrencyRate

    try:
        latest = CurrencyRate.objects.filter(
            base_currency=base_currency,
            target_currency=target_currency
        ).first()  # Already ordered by -id, so first() gets latest

        if latest:
            logger.info(
                f"Retrieved rate from database: 1 {base_currency} = {latest.rate} {target_currency} "
                f"(created: {latest.created_at})"
            )
            return latest.rate
        else:
            logger.warning(
                f"No exchange rate found in database for {base_currency}/{target_currency}"
            )
            return None

    except Exception as e:
        logger.error(f"Error retrieving exchange rate: {e}")
        return None


def get_exchange_rate():
    """
    Get current exchange rate from database.
    This is called during payment processing.

    Returns:
        Decimal: Exchange rate (1 USD = X HKD)
    """
    # Get latest rate from database
    rate = get_latest_rate()

    if rate is None:
        logger.warning(f"No rate in database, using fallback: {FALLBACK_RATE}")
        rate = FALLBACK_RATE

    logger.info(f"Using exchange rate: 1 USD = {rate} HKD")

    return rate


def convert_hkd_to_usd(amount_hkd):
    """
    Convert HKD amount to USD using database exchange rate.

    Args:
        amount_hkd: Amount in HKD (Decimal or float)

    Returns:
        tuple: (amount_usd, exchange_rate_used)
    """
    if not isinstance(amount_hkd, Decimal):
        amount_hkd = Decimal(str(amount_hkd))

    exchange_rate = get_exchange_rate()
    amount_usd = (amount_hkd / exchange_rate).quantize(Decimal('0.01'))

    logger.info(
        f"Currency conversion: HKD {amount_hkd} → USD {amount_usd} "
        f"(rate: 1 USD = {exchange_rate} HKD)"
    )

    return amount_usd, exchange_rate


def get_payment_currency(payment_method):
    """
    Determine which currency to use for a given payment method.

    Args:
        payment_method: Payment method identifier

    Returns:
        str: 'HKD' or 'USD'
    """
    if payment_method == 'alipay':
        return 'USD'
    return 'HKD'


def get_stripe_currency(payment_method):
    """
    Get the Stripe currency code for a payment method.

    Args:
        payment_method: Payment method identifier

    Returns:
        str: Stripe currency code ('hkd' or 'usd')
    """
    currency = get_payment_currency(payment_method)
    return currency.lower()


def cleanup_old_rates(days_to_keep=90):
    """
    Delete exchange rates older than specified days.
    Keeps database from growing indefinitely.

    Args:
        days_to_keep: Number of days of history to retain

    Returns:
        int: Number of records deleted
    """
    from currency.models import CurrencyRate
    from datetime import timedelta

    cutoff_date = timezone.now() - timedelta(days=days_to_keep)

    deleted_count, _ = CurrencyRate.objects.filter(
        created_at__lt=cutoff_date
    ).delete()

    if deleted_count > 0:
        logger.info(
            f"Cleaned up {deleted_count} exchange rate records older than {days_to_keep} days"
        )

    return deleted_count


def get_rate_history(base_currency='USD', target_currency='HKD', days=30):
    """
    Get historical rates for charting/analysis.

    Args:
        base_currency: Source currency
        target_currency: Target currency
        days: Number of days of history

    Returns:
        QuerySet: CurrencyRate objects ordered by created_at
    """
    from currency.models import CurrencyRate
    from datetime import timedelta

    start_date = timezone.now() - timedelta(days=days)

    return CurrencyRate.objects.filter(
        base_currency=base_currency,
        target_currency=target_currency,
        created_at__gte=start_date
    ).order_by('created_at')


def get_rate_info():
    """
    Get detailed information about current exchange rate.
    Useful for admin dashboard or debugging.

    Returns:
        dict: Information about current rate
    """
    from currency.models import CurrencyRate

    try:
        latest = CurrencyRate.objects.filter(
            base_currency='USD',
            target_currency='HKD'
        ).first()

        if latest:
            age_hours = (timezone.now() - latest.created_at).total_seconds() / 3600

            return {
                'rate': latest.rate,
                'created_at': latest.created_at,
                'updated_at': latest.updated_at,
                'age_hours': age_hours,
                'is_fresh': age_hours < 24,  # Less than 24 hours old
            }
        else:
            return {
                'rate': None,
                'message': 'No exchange rate in database',
            }
    except Exception as e:
        logger.error(f"Error getting rate info: {e}")
        return {
            'rate': None,
            'error': str(e),
        }


def send_exchange_rate_alert(message):
    """
    Send alert email when exchange rate update fails.

    Args:
        message: Alert message to send
    """
    try:
        from django.core.mail import mail_admins
        from datetime import datetime

        mail_admins(
            subject='[ALERT] Exchange Rate Update Issue',
            message=(
                f'{message}\n\n'
                f'Time: {datetime.now()}\n\n'
                'Please check:\n'
                '1. ExchangeRate-API service status\n'
                '2. Network connectivity\n'
                '3. API key configuration (if using paid tier)\n'
                '4. Server logs for details\n'
            ),
            fail_silently=True
        )

        logger.info("Exchange rate alert email sent to admins")
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")