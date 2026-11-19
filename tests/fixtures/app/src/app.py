# @trace docs/development/rules.md#max-discount
def discount(order):
    return max(order.discounts, default=0)
