from django import template

register = template.Library()


@register.filter(nam="calc_subtotal")
def calc_subtotal(price, quantity):
    return price * quantity