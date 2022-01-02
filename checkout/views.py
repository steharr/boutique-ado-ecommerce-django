from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.contrib import messages
from django.conf import settings
from django.views.decorators.http import require_POST
from django.http import HttpResponse

from .forms import OrderForm
from .models import Order, OrderLineItem
from products.models import Product
from bag.contexts import bag_contents

import stripe
import json


@require_POST
def cache_checkout_data(request):
    try:
        # give this view the client secret from the payment intent
        # split at word secret so that first part is payment intent id
        pid = request.POST.get('client_secret').split('_secret')[0]
        stripe.api_key = settings.STRIPE_SECRET_KEY
        stripe.PaymentIntent.modify(pid,
                                    metadata={
                                        'bag':
                                        json.dumps(
                                            request.session.get('bag', {})),
                                        'save_info':
                                        request.POST.get('save_info'),
                                        'username':
                                        request.user,
                                    })
    except Exception as e:
        messages.error(
            request, 'Sorry, your payment cannot be  \
                processed right now, Please try again later.')
        return HttpResponse(content=e, status=400)
    return HttpResponse(status=200)


def checkout(request):
    stripe_public_key = settings.STRIPE_PUBLIC_KEY
    stripe_secret_key = settings.STRIPE_SECRET_KEY

    if request.method == 'POST':
        # add the data into a dictionary to be sent to db
        bag = request.session.get('bag', {})
        form_data = {
            'full_name': request.POST['full_name'],
            'email': request.POST['email'],
            'phone_number': request.POST['phone_number'],
            'country': request.POST['country'],
            'postcode': request.POST['postcode'],
            'town_or_city': request.POST['town_or_city'],
            'street_address1': request.POST['street_address1'],
            'street_address2': request.POST['street_address2'],
            'county': request.POST['county'],
        }
        order_form = OrderForm(form_data)
        if order_form.is_valid():

            # validated form so can save it to db and
            # commit = false, create the instance but dont commit to db yet
            order = order_form.save(commit=False)

            # get the payment intent id to add to entry in db
            pid = request.POST.get('client_secret').split('_secret')[0]
            order.stripe_pid = pid
            # get the original bag to add to entry in db
            order.original_bag = json.dumps(bag)

            # save and commit order to db
            order.save()

            # iterate through bag items to create each line item
            for item_id, item_data in bag.items():
                try:
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
                except Product.DoesNotExist:
                    messages.error(request, (
                        "One of the products in your bag wasn't found in our database."
                        "Please call us for assistance!"))
                    order.delete()
                    return redirect(reverse('view_bag'))

            request.session['save_info'] = 'save_info' in request.POST
            return redirect(
                reverse('checkout_success', args=[order.order_number]))
        else:
            messages.error(
                request, 'There is an error with your form \
                Please double check your information')

    else:
        # if theres no data being posted to db yet,
        # this block sets up vars for rendering the checkout template
        # it also creates a stripe payment intent object (on stripe's servers) -> identified by a secret key
        bag = request.session.get('bag', {})
        if not bag:
            messages.error(request,
                           "There's nothing in your bag at the moment")
            return redirect(reverse('products'))

        current_bag = bag_contents(request)
        total = current_bag['grand_total']
        stripe_total = round(total * 100)
        stripe.api_key = stripe_secret_key

        # intent created here - stripe creates a unique client secret
        # which is returned as part of the intent object
        # that client secret is important for later
        intent = stripe.PaymentIntent.create(amount=stripe_total,
                                             currency=settings.STRIPE_CURRENCY)
        order_form = OrderForm()

    if not stripe_public_key:
        messages.warning(
            request,
            'Stripe public key is missing. Did you forget to set it in your environment?'
        )

    template = 'checkout/checkout.html'
    context = {
        'order_form': order_form,
        'stripe_public_key': stripe_public_key,
        'client_secret': intent.client_secret,
    }

    return render(request, template, context)


def checkout_success(request, order_number):
    """
    Handle successful checkouts
    """
    save_info = request.session.get('save_info')
    order = get_object_or_404(Order, order_number=order_number)
    messages.success(
        request, f'Order successfully processed! \
        your order number is {order_number}. A confirmation will be sent to {order.email}'
    )

    if 'bag' in request.session:
        del request.session['bag']

    template = 'checkout/checkout_success.html'
    context = {
        'order': order,
    }

    return render(request, template, context)