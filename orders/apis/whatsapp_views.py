"""
WhatsApp Order Integration - Backend Views

How it works:
1. Customer selects WhatsApp at checkout → frontend calls /api/orders/whatsapp/create/
2. Backend creates a pending Order and generates a WhatsApp deep link with pre-filled message
3. Customer clicks the link → WhatsApp opens with order details pre-filled
4. Customer sends the message → our staff receives the order
5. Admin manually confirms payment in Django admin panel after customer pays
6. System sends order confirmation email automatically
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from decimal import Decimal
import urllib.parse
import logging

from .serializers import CheckoutSerializer
from ..models import Order

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Region and District Name Mappings
# ─────────────────────────────────────────────────────────────────────────────

HONG_KONG_REGIONS = {
    'hong-kong-island': {'zh': '香港島', 'en': 'Hong Kong Island'},
    'kowloon': {'zh': '九龍', 'en': 'Kowloon'},
    'new-territories': {'zh': '新界', 'en': 'New Territories'},
}

HONG_KONG_DISTRICTS = {
    'hong-kong-island': {
        'central-and-western': {'zh': '中西區', 'en': 'Central & Western'},
        'eastern': {'zh': '東區', 'en': 'Eastern'},
        'southern': {'zh': '南區', 'en': 'Southern'},
        'wan-chai': {'zh': '灣仔區', 'en': 'Wan Chai'},
    },
    'kowloon': {
        'sham-shui-po': {'zh': '深水埗區', 'en': 'Sham Shui Po'},
        'yau-tsim-mong': {'zh': '油尖旺區', 'en': 'Yau Tsim Mong'},
        'shatin': {'zh': '沙田區', 'en': 'Sha Tin'},
        'kowloon-city': {'zh': '九龍城區', 'en': 'Kowloon City'},
        'wong-tai-sin': {'zh': '黃大仙區', 'en': 'Wong Tai Sin'},
        'kwun-tong': {'zh': '觀塘區', 'en': 'Kwun Tong'},
    },
    'new-territories': {
        'kwai-tsing': {'zh': '葵青區', 'en': 'Kwai Tsing'},
        'tsuen-wan': {'zh': '荃灣區', 'en': 'Tsuen Wan'},
        'tuen-mun': {'zh': '屯門區', 'en': 'Tuen Mun'},
        'yuen-long': {'zh': '元朗區', 'en': 'Yuen Long'},
        'north': {'zh': '北區', 'en': 'North'},
        'tai-po': {'zh': '大埔區', 'en': 'Tai Po'},
        'sha-tin': {'zh': '沙田區', 'en': 'Sha Tin'},
        'sai-kung': {'zh': '西貢區', 'en': 'Sai Kung'},
        'islands': {'zh': '離島區', 'en': 'Islands'},
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp Link Builder
# ─────────────────────────────────────────────────────────────────────────────

def build_whatsapp_link(order_number: str, customer_name: str, amount_hkd: Decimal,
                        items: list, delivery_address: str, delivery_region: str, delivery_district: str, delivery_date: str,
                        language: str = 'en') -> dict:
    """
    Build a WhatsApp deep link that pre-fills the message with order details.
    
    WhatsApp Deep Link format:
    https://wa.me/<phone>?text=<url-encoded-message>
    
    Or using the older format:
    https://api.whatsapp.com/send?phone=<phone>&text=<url-encoded-message>
    
    Parameters:
    - language: 'zh-HK' for Chinese, 'en' for English (default: 'en')
    """
    # Get WhatsApp phone number from settings
    whatsapp_phone = getattr(settings, 'WHATSAPP_PHONE_NUMBER', '')
    
    # Strip any non-digit characters
    phone_digits = ''.join(filter(str.isdigit, whatsapp_phone))
    
    # Build the order details message
    items_text = "\n".join([
        f"- {item.get('name', 'Product')}{' (' + item.get('option_name', '') + ')' if item.get('option_name') else ''} x{item.get('quantity', 1)}"
        for item in items
    ])

    # Get translated region and district names
    lang_key = 'zh' if language == 'zh-HK' else 'en'
    region_name = HONG_KONG_REGIONS.get(delivery_region, {}).get(lang_key, delivery_region)
    district_name = HONG_KONG_DISTRICTS.get(delivery_region, {}).get(delivery_district, {}).get(lang_key, delivery_district)

    # Build address with region and district
    if district_name and district_name != delivery_district:
        full_address = f"{delivery_address}\n({district_name}, {region_name})"
    elif region_name and region_name != delivery_region:
        full_address = f"{delivery_address}\n({region_name})"
    else:
        full_address = delivery_address

    # Build message based on language
    if language == 'zh-HK':
        # Chinese message
        message = (
            f"新訂單 - 風信子花店\n\n"
            f"訂單編號: {order_number}\n"
            f"客戶姓名: {customer_name}\n"
            f"總金額: HK${amount_hkd:.2f}\n\n"
            f"訂單詳情:\n{items_text}\n\n"
            f"送貨地址:\n{full_address}\n\n"
            f"送貨日期:\n{delivery_date}\n\n"
            f"請確認付款詳情。感謝您的訂單！"
        )
    else:
        # English message
        message = (
            f"New Order - Hyacinth Florist\n\n"
            f"Order Number: {order_number}\n"
            f"Customer: {customer_name}\n"
            f"Total Amount: HK${amount_hkd:.2f}\n\n"
            f"Order Items:\n{items_text}\n\n"
            f"Delivery Address:\n{full_address}\n\n"
            f"Delivery Date:\n{delivery_date}\n\n"
            f"Please confirm payment details. Thank you!"
        )
    
    # URL encode the message
    encoded_message = urllib.parse.quote(message, safe='')
    
    # Build the WhatsApp link (using wa.me which is the modern format)
    if phone_digits:
        whatsapp_link = f"https://wa.me/{phone_digits}?text={encoded_message}"
    else:
        # Fallback to api.whatsapp.com format
        whatsapp_link = f"https://api.whatsapp.com/send?phone={phone_digits}&text={encoded_message}"
    
    return {
        'whatsapp_link': whatsapp_link,
        'amount_hkd': float(amount_hkd),
    }


# ─────────────────────────────────────────────────────────────────────────────
# View: Create WhatsApp Order
# ─────────────────────────────────────────────────────────────────────────────

class CreateWhatsAppOrderView(APIView):
    """
    POST /api/orders/whatsapp/create/
    
    Creates a pending Order and returns the WhatsApp deep link with pre-filled message.
    
    Request body: same as Stripe checkout (customer info + items).
    Response: order_number, whatsapp_link, amount_hkd
    """
    
    def post(self, request):
        try:
            serializer = CheckoutSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"WhatsApp order - invalid data: {serializer.errors}")
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            subtotal, delivery_fee, discount, total_hkd = serializer.calculate_order_total()
            
            if total_hkd <= 0:
                return Response(
                    {'error': '訂單金額無效'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get items for the WhatsApp message
            items_data = []
            for item in serializer.validated_data.get('items', []):
                product_id = item.get('product_id')
                from products.models import Product
                try:
                    product = Product.objects.get(id=product_id)
                    product_name = product.name
                except Product.DoesNotExist:
                    product_name = f"Product #{product_id}"
                
                # Get option name if selected
                option_name = None
                selected_option_id = item.get('selected_option_id')
                if selected_option_id:
                    try:
                        from products.models import ProductOption
                        option = ProductOption.objects.get(id=selected_option_id, product=product)
                        option_name = option.name
                    except ProductOption.DoesNotExist:
                        pass
                
                items_data.append({
                    'name': product_name,
                    'quantity': item.get('quantity', 1),
                    'option_name': option_name,
                })
            
            # Create the order in PENDING state (not paid yet)
            with transaction.atomic():
                order = serializer.create_order(
                    stripe_payment_intent_id=None,
                    payment_method='whatsapp',
                    payment_currency='HKD',
                    exchange_rate=None,
                    total_usd=None,
                )
                # Keep status pending — admin confirms after customer contacts via WhatsApp
                order.payment_status = 'pending'
                order.status = 'pending'
                order.save(update_fields=['payment_status', 'status', 'updated_at'])
            
            # Build WhatsApp link
            language = serializer.validated_data.get('language', 'en')
            whatsapp_data = build_whatsapp_link(
                order_number=order.order_number,
                customer_name=serializer.validated_data.get('customer_name', 'Customer'),
                amount_hkd=total_hkd,
                items=items_data,
                delivery_address=serializer.validated_data.get('delivery_address', ''),
                delivery_region=serializer.validated_data.get('delivery_region', ''),
                delivery_district=serializer.validated_data.get('delivery_district', ''),
                delivery_date=serializer.validated_data.get('delivery_date', ''),
                language=language,
            )
            
            logger.info(
                f"WhatsApp order created: {order.order_number}, "
                f"Amount: HK${total_hkd}, Link: {whatsapp_data['whatsapp_link']}"
            )
            
            return Response({
                'order_number': order.order_number,
                'whatsapp_link': whatsapp_data['whatsapp_link'],
                'amount_hkd': whatsapp_data['amount_hkd'],
                'message': (
                    '感謝您的訂單！請透過 WhatsApp 聯繫我們確認訂單詳情。'
                    '我們會提供付款指示，確認付款後將發送確認電郵。'
                ) if serializer.validated_data.get('language', 'zh-HK') == 'zh-HK' else (
                    'Thank you for your order! Please contact us via WhatsApp to confirm your order details. '
                    'We will provide payment instructions and send a confirmation email once payment is confirmed.'
                ),
            })
            
        except Exception as e:
            logger.error(f"WhatsApp order creation error: {str(e)}")
            return Response(
                {'error': '無法建立訂單，請稍後再試'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
