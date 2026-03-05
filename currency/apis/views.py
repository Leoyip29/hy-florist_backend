from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from currency.models import CurrencyRate
import logging

logger = logging.getLogger(__name__)


class LatestExchangeRateView(APIView):
    """
    Get the latest USD to HKD exchange rate.

    Used by frontend to display exchange rate BEFORE creating Payment Intent.
    This allows users to see the conversion rate when choosing payment methods.
    """

    def get(self, request):
        try:
            # Get latest exchange rate
            currency_rate = CurrencyRate.objects.filter(
                base_currency='USD',
                target_currency='HKD'
            ).order_by('-created_at').first()

            if not currency_rate:
                logger.error("No USD to HKD exchange rate found")
                return Response(
                    {'error': 'Exchange rate not available'},
                    status=status.HTTP_404_NOT_FOUND
                )

            return Response({
                'base_currency': 'USD',
                'target_currency': 'HKD',
                'rate': float(currency_rate.rate),
                'updated_at': currency_rate.created_at.isoformat(),
            })

        except Exception as e:
            logger.error(f"Error fetching exchange rate: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to fetch exchange rate'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

