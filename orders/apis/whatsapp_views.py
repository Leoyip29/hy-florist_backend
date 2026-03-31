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
import traceback

from .serializers import CheckoutSerializer
from ..models import Order

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Location Name Mappings (Funeral Parlours & Churches)
# ─────────────────────────────────────────────────────────────────────────────

LOCATION_NAMES = {
    # 殯儀館
    "hk-island-hkf": {"zh": "香港殯儀館（北角）", "en": "Hong Kong Funeral Parlour (North Point)"},
    "kowloon-world": {"zh": "世界殯儀館", "en": "World Funeral Parlour"},
    "kowloon-international": {"zh": "萬國殯儀館", "en": "International Funeral Parlour"},
    "kowloon-cosmos": {"zh": "寰宇殯儀館", "en": "Cosmos Funeral Parlour"},
    "kowloon-kowloon": {"zh": "九龍殯儀館", "en": "Kowloon Funeral Parlour"},
    "kowloon-diamond-hill": {"zh": "鑽石山殯儀館", "en": "Diamond Hill Funeral Parlour"},
    "nt-po-fook": {"zh": "寶福紀念館（大圍）", "en": "Po Fook Memorial Hall (Sha Tin)"},
    # 教堂
    "kowloon-st-andrew": {"zh": "聖安德烈堂", "en": "St. Andrew's Church"},
    "kowloon-st-john": {"zh": "聖公會聖匠堂", "en": "St. John's Church"},
    "kowloon-shum-ao": {"zh": "中華基督教會深愛堂", "en": "Shum Ao Church"},
    "hk-island-wan-chai": {"zh": "灣仔聯合教會國際禮拜堂", "en": "Wan Chai United Church International Chapel"},
    "hk-island-north-point": {"zh": "北角衛斯理堂", "en": "North Point Wesley Church"},
    "hk-island-pokfulam": {"zh": "薄扶林上路教堂", "en": "Pokfulam Road Church"},
    "hk-island-hk-union": {"zh": "香港佑寧堂", "en": "Hong Kong Union Church"},
    "tko-haven": {"zh": "靈實禮拜堂", "en": "Haven of Hope Chapel"},
    "tko-st-john-baptist": {"zh": "施洗聖約翰堂", "en": "St. John the Baptist Church"},
    "nt-tuen-mun": {"zh": "屯門神召會神學院", "en": "Tuen Mun Christian Academy"},
    "nt-jockey-club": {"zh": "賽馬會善寧之家", "en": "Jockey Club Tseng's Home"},
}


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp Link Builder
# ─────────────────────────────────────────────────────────────────────────────

def build_whatsapp_link(
        order_number: str,
        customer_name: str,
        customer_email: str,
        customer_phone: str,
        deceased_name: str,
        amount_hkd: Decimal,
        subtotal: Decimal,
        delivery_fee: Decimal,
        items: list,
        delivery_address: str,
        delivery_region: str,
        delivery_district: str,
        delivery_date: str,
        delivery_notes: str = '',
        language: str = 'en',
) -> dict:
    """
    Build a WhatsApp deep link that pre-fills the message with order details.
    Bilingual format: Chinese and English side by side (中英對照)
    """
    # Get WhatsApp phone number from settings
    whatsapp_phone = getattr(settings, 'WHATSAPP_PHONE_NUMBER', '')

    # Strip any non-digit characters
    phone_digits = ''.join(filter(str.isdigit, whatsapp_phone))

    # Build per-item breakdown text (bilingual)
    separator = "____________\n"
    items_text_parts = []
    for i, item in enumerate(items):
        name_en = item.get('name', 'Product')
        option_en = item.get('option_name', '')
        name_zh = item.get('name_zh', name_en)
        option_zh = item.get('option_name_zh', option_en)

        item_lines = []
        # Item header with both languages
        item_lines.append(f"{i + 1}. {name_zh} / {name_en}")
        if option_en:
            item_lines.append(f"   ({option_zh} / {option_en})")
        item_lines.append(f"   數量 Qty: {item.get('quantity', 1)}")
        item_lines.append(f"   單價 Unit Price: HKD${item.get('unit_price', 0):.2f}")
        item_lines.append(f"   小計 Subtotal: HKD${item.get('line_total', 0):.2f}")
        items_text_parts.append("\n".join(item_lines))

    items_text = separator + "\n".join(items_text_parts) + "\n" + separator

    # Get translated location name (bilingual)
    location_zh = LOCATION_NAMES.get(delivery_district, {}).get('zh', delivery_district)
    location_en = LOCATION_NAMES.get(delivery_district, {}).get('en', delivery_district)

    # Build address with location name (bilingual)
    if location_en and location_en != delivery_district:
        full_address = f"{delivery_address}\n({location_zh} / {location_en})"
    else:
        full_address = f"{delivery_address}"

    # Delivery fee display
    delivery_fee_text = "HKD$0" if delivery_fee == 0 else f"HKD${delivery_fee:.2f}"

    # Build bilingual message (always show both Chinese and English)
    message = (
        f"🌸 新訂單 New Order - 風信子花店 Hyacinth Florist\n"
        f"{separator}\n"
        f"客戶姓名 Customer: {customer_name}\n"
        f"電郵 Email: {customer_email}\n"
        f"電話 Phone: {customer_phone}\n"
        f"先人姓名 Deceased: {deceased_name}\n"
        f"{separator}\n"
        f"送貨地址 Delivery Address:\n{full_address}\n\n"
        f"送貨日期 Delivery Date: {delivery_date}\n"
    )

    # Notes section (bilingual)
    if delivery_notes and delivery_notes.strip():
        message += f"\n備註 Notes:\n{delivery_notes.strip()}\n"

    message += (
        f"{separator}\n"
        f"{items_text}\n"
        f"運費 Delivery Fee: {delivery_fee_text}\n"
        f"小計 Subtotal: HKD${subtotal:.2f}\n"
        f"總計 Total: HKD${amount_hkd:.2f}\n"
        f"{separator}\n"
        f"請確認付款詳情。感謝您的訂單！\n"
        f"Please confirm payment details. Thank you!\n"
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
            
            # Get items for the WhatsApp message (with per-item pricing)
            from products.models import Product, ProductOption
            items_data = []
            for item in serializer.validated_data.get('items', []):
                product_id = item.get('product_id')
                try:
                    product = Product.objects.get(id=product_id)
                    product_name_en = product.name
                    # Try to get Chinese name from categories or use English name
                    product_name_zh = product_name_en
                    for cat in product.categories.all():
                        if cat.name_en:
                            product_name_zh = product_name_en
                            break
                except Product.DoesNotExist:
                    product_name_en = f"Product #{product_id}"
                    product_name_zh = product_name_en
                    product = None

                quantity = item.get('quantity', 1)
                unit_price = Decimal('0')
                option_name_en = None
                option_name_zh = None

                selected_option_id = item.get('selected_option_id')
                if selected_option_id and product:
                    try:
                        option = ProductOption.objects.get(id=selected_option_id, product=product)
                        option_name_en = option.name
                        option_name_zh = option.name  # Use same name if no Chinese version
                        unit_price = Decimal(str(product.price)) + Decimal(str(option.price_adjustment))
                    except ProductOption.DoesNotExist:
                        unit_price = Decimal(str(product.price))
                elif product:
                    unit_price = Decimal(str(product.price))

                line_total = unit_price * quantity

                items_data.append({
                    'name': product_name_en,
                    'name_zh': product_name_zh,
                    'quantity': quantity,
                    'option_name': option_name_en,
                    'option_name_zh': option_name_zh,
                    'unit_price': unit_price,
                    'line_total': line_total,
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
            # Use delivery_district as the address name if delivery_address is empty
            raw_address = serializer.validated_data.get('delivery_address', '')
            district = serializer.validated_data.get('delivery_district', '')
            lang_key = 'zh' if language == 'zh-HK' else 'en'
            if district and not raw_address:
                raw_address = LOCATION_NAMES.get(district, {}).get(lang_key, district)
            whatsapp_data = build_whatsapp_link(
                order_number=order.order_number,
                customer_name=serializer.validated_data.get('customer_name', 'Customer'),
                customer_email=serializer.validated_data.get('customer_email', ''),
                customer_phone=serializer.validated_data.get('customer_phone', ''),
                deceased_name=serializer.validated_data.get('deceased_name', ''),
                amount_hkd=total_hkd,
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                items=items_data,
                delivery_address=raw_address,
                delivery_region=serializer.validated_data.get('delivery_region', ''),
                delivery_district=district,
                delivery_date=serializer.validated_data.get('delivery_date', ''),
                delivery_notes=serializer.validated_data.get('delivery_notes', ''),
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
            logger.error(f"WhatsApp order creation error: {str(e)}\n{traceback.format_exc()}")
            return Response(
                {'error': '無法建立訂單，請稍後再試'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
