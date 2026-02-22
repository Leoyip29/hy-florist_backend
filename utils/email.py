# orders/email_utils.py

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def send_order_confirmation_email(order):
    """
    Send a bilingual order confirmation email.
    Language is determined by order.language ('en' or 'zh-HK').
    """
    subject = (
        f'Order Confirmation - #{order.order_number}'
        if order.language == 'en'
        else f'訂單確認 - #{order.order_number}'
    )

    context = {
        'order': order,
        'items': order.items.all(),
        'company_name': 'HY Florist',
        'support_email': settings.DEFAULT_FROM_EMAIL,
        'year': timezone.now().year,
    }

    html_message = render_to_string('emails/order_confirmation.html', context)
    plain_message = strip_tags(html_message)

    send_mail(
        subject=subject,
        message=plain_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[order.customer_email],
        html_message=html_message,
        fail_silently=False,
    )

    logger.info(
        f"Confirmation email sent for order {order.order_number} "
        f"(language: {order.language}, email: {order.customer_email})"
    )