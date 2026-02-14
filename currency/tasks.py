"""
Huey Tasks for Currency Exchange Rate Updates
Scheduled task runs daily at midnight to fetch latest rates
"""
from huey import crontab
from huey.contrib.djhuey import db_periodic_task, db_task
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@db_periodic_task(crontab(hour='0', minute='0'))  # Runs daily at midnight (00:00)
def update_exchange_rate_task():
    """
    Scheduled task: Fetch and update exchange rate daily at midnight.

    This task:
    1. Fetches latest USD/HKD rate from ExchangeRate-API
    2. Stores it in the Currency table
    3. Sends alert if fetch fails
    4. Cleans up old rates (keeps 90 days)
    """
    from utils.currency_service import update_exchange_rate

    logger.info("=" * 70)
    logger.info("Starting scheduled exchange rate update (midnight cron)")
    logger.info("=" * 70)

    try:
        success, rate, message = update_exchange_rate()

        if success:
            logger.info(f"✓ Exchange rate update successful: {message}")
        else:
            logger.warning(f"⚠ Exchange rate update failed: {message}")

        logger.info("=" * 70)
        logger.info(f"Exchange rate update completed at {datetime.now()}")
        logger.info("=" * 70)

        return {
            'success': success,
            'rate': float(rate) if rate else None,
            'message': message,
            'timestamp': datetime.now().isoformat(),
        }

    except Exception as e:
        error_msg = f"Critical error in exchange rate update task: {str(e)}"
        logger.error(error_msg, exc_info=True)

        return {
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat(),
        }
