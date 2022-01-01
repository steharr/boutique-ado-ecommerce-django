from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from checkout.webhook_handler import StripeWH_Handler

import stripe


@require_POST
@csrf_exempt
def webhook(request):
    """Listen for webhooks from Stripe"""
    # setup
    wh_secret = settings.STRIPE_WH_SECRET
    stripe.api_key = settings.STRIPE_SECRET_KEY

    # get the webhook data and verify its signature
    payload = request.body
    sig_header = request.META['HTTP_STRIPE_SIGNATURE']
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            wh_secret,
        )
    except ValueError as e:
        # Invalid payload
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid Signature
        return HttpResponse(status=400)
    except Exception as e:
        return HttpResponse(content=e, status=400)

    # set up the webhook handler
    handler = StripeWH_Handler(request)

    # map webhook events to relevant handler functions
    # maps event type -> event handler method to be called
    event_map = {
        'payment_intent.succeeded':
        handler.handle_payment_intent_succeded,
        'payment_intent.payment_failed':
        handler.handle_payment_intent_payment_failed,
    }

    # get the type of webhook from stripe
    event_type = event['type']

    # look up dict 'event_map' and assign its value to an event handler
    # use generic 'handle_event' method if event not in dictionary
    event_handler = event_map.get(event_type, handler.handle_event)

    # call the event_handler with the event
    response = event_handler(event)

    return response