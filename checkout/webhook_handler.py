from django.http import HttpResponse

from profiles.models import UserProfile
from .models import Order, OrderLineItem
from products.models import Product

import json
import time


class StripeWH_Handler():
    """Handle Stripe WebHooks"""
    def __init__(self, request):
        self.request = request

    def handle_event(self, event):
        """
        Handle a generic/unknown/unexpected webhook event
        """
        return HttpResponse(
            content=f"Unhandled webhook recieved: {event['type']}", status=200)

    def handle_payment_intent_succeded(self, event):
        """
        Handle a payment_intent.succeded webhook from Stripe
        """
        intent = event.data.object
        pid = intent.id
        bag = intent.metadata.bag
        save_info = intent.metadata.save_info
        billing_details = intent.charges.data[0].billing_details
        shipping_details = intent.shipping
        grand_total = round(intent.charges.data[0].amount / 100, 2)

        # replace blank address information as None for database
        # stripes stores as ""
        for field, value in shipping_details.address.items():
            if value == "":
                shipping_details.address[field] = None

        # Update profile information if save_info was checked
        profile = None
        username = intent.metadata.username
        if username != "AnonymousUser":
            profile = UserProfile.objects.get(user__username=username)
            if save_info:
                profile.default_phone_number = shipping_details.phone
                profile.default_country = shipping_details.address.country
                profile.default_postcode = shipping_details.address.postal_code
                profile.default_town_or_city = shipping_details.address.city
                profile.default_street_address1 = shipping_details.address.line1
                profile.default_street_address2 = shipping_details.address.line2
                profile.default_county = shipping_details.address.state
                profile.save()

        # check if order exists or not
        # if it does -> return response all good
        # otherwise ->

        # start as false
        order_exists = False

        attempt = 1
        while attempt <= 5:
            try:  # try to find the order in the database
                order = Order.objects.get(
                    full_name__iexact=shipping_details.name,
                    email__iexact=billing_details.email,
                    phone_number__iexact=shipping_details.phone,
                    # --
                    country__iexact=shipping_details.address.country,
                    postcode__iexact=shipping_details.address.postal_code,
                    town_or_city__iexact=shipping_details.address.city,
                    street_address1__iexact=shipping_details.address.line1,
                    street_address2__iexact=shipping_details.address.line2,
                    county__iexact=shipping_details.address.state,
                    # --
                    grand_total__iexact=grand_total,
                    stripe_pid=pid,
                    original_bag=bag,
                )
                order_exists = True
                break

            except Order.DoesNotExist:  # its not there, wait 1 second and incremt the attempts made
                attempt += 1
                time.sleep(1)

        if order_exists:  # if the order exists, return 200
            return HttpResponse(
                content=
                f"Webhook recieved: {event['type']} | SUCCESS: Verified order already in database",
                status=200)
        else:  # if it doesnt exist, use data in payment intent to create
            order = None
            try:
                # then create the order in the database
                order = Order.objects.create(
                    full_name=shipping_details.name,
                    user_profile=profile,
                    email=billing_details.email,
                    phone_number=shipping_details.phone,
                    # --
                    country=shipping_details.address.country,
                    postcode=shipping_details.address.postal_code,
                    town_or_city=shipping_details.address.city,
                    street_address1=shipping_details.address.line1,
                    street_address2=shipping_details.address.line2,
                    county=shipping_details.address.state,
                    # --
                    stripe_pid=pid,
                    original_bag=bag,
                )
                # iterate through bag items to create each line item
                for item_id, item_data in json.loads(bag).items():
                    product = Product.objects.get(id=item_id)
                    # if its a single item (one size)
                    if isinstance(item_data, int):
                        order_line_item = OrderLineItem(
                            order=order,
                            product=product,
                            quantity=item_data,
                        )
                        order_line_item.save()
                    # if its multiple items by size
                    else:
                        for size, quantity in item_data['items_by_size'].items(
                        ):
                            order_line_item = OrderLineItem(
                                order=order,
                                product=product,
                                quantity=quantity,
                                product_size=size,
                            )
                            order_line_item.save()
            except Exception as e:
                if order:
                    order.delete()
                return HttpResponse(
                    content=f"Webhook recieved: {event['type']} | ERROR: {e}",
                    status=500)

        return HttpResponse(
            content=
            f"Webhook recieved: {event['type']} | SUCCESS: Order created by webhook in database",
            status=200)

    def handle_payment_intent_payment_failed(self, event):
        """
        Handle a payment_intent.payment_failed webhook from Stripe
        """
        return HttpResponse(
            content=f"Payment Failed Webhook recieved: {event['type']}",
            status=200)
