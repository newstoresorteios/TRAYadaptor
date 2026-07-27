from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.identifiers import normalize_optional_variant_id
from app.normalizers.cart import normalize_cart
from app.resources.shippings import _quote_params
from app.schemas.carts import CartItemQuantityUpdateRequest
from app.schemas.orders import OrderProduct, OrderShipping
from app.schemas.shippings import ShippingQuoteProduct, ShippingQuoteRequest


@pytest.mark.parametrize("value", [None, "", 0, "0"])
def test_optional_variant_id_canonicalizes_absence_sentinels(value):
    assert normalize_optional_variant_id(value) is None


@pytest.mark.parametrize("value", [123, "123"])
def test_optional_variant_id_canonicalizes_positive_ids(value):
    assert normalize_optional_variant_id(value) == 123


@pytest.mark.parametrize("value", [True, -1, "-1", "invalid", "1.5"])
def test_optional_variant_id_rejects_invalid_write_values(value):
    with pytest.raises(ValueError):
        normalize_optional_variant_id(value)


def test_cart_normalizer_canonicalizes_products_and_simple_cart_variants():
    complete = normalize_cart(
        {
            "Cart": {
                "Products": [
                    {
                        "product_id": "803",
                        "variant_id": "0",
                        "quantity": "1",
                        "price": "3999.99",
                    },
                    {
                        "product_id": "804",
                        "variant_id": "123",
                        "quantity": "1",
                        "price": "100.00",
                    },
                ]
            }
        }
    )
    simple_without_variant = normalize_cart(
        {
            "Cart": {
                "product_id": "803",
                "variant_id": "0",
                "quantity": "1",
                "price": "3999.99",
            }
        }
    )
    simple_with_variant = normalize_cart(
        {
            "Cart": {
                "product_id": "804",
                "variant_id": "123",
                "quantity": "1",
                "price": "100.00",
            }
        }
    )

    assert complete["items"][0]["product_id"] == "803"
    assert "variant_id" not in complete["items"][0]
    assert complete["items"][0]["quantity"] == 1
    assert complete["items"][0]["price"] == 3999.99
    assert complete["items"][1]["variant_id"] == 123
    assert "variant_id" not in simple_without_variant
    assert simple_with_variant["variant_id"] == 123


def test_cart_to_shipping_contract_chain_accepts_tray_zero_without_sku():
    cart = normalize_cart(
        {
            "Cart": {
                "Products": [
                    {
                        "product_id": "803",
                        "variant_id": "0",
                        "quantity": "1",
                        "price": "3999.99",
                    }
                ]
            }
        }
    )
    item = cart["items"][0]
    quote = ShippingQuoteRequest.model_validate(
        {
            "zipcode": "86480000",
            "products": [
                {
                    "product_id": item["product_id"],
                    "variant_id": item.get("variant_id"),
                    "price": item["price"],
                    "quantity": item["quantity"],
                }
            ],
        }
    )
    payload = quote.model_dump(exclude_none=True)
    params = _quote_params(payload)

    assert payload == {
        "zipcode": "86480000",
        "products": [
            {
                "product_id": 803,
                "price": Decimal("3999.99"),
                "quantity": 1,
            }
        ],
    }
    assert params["products[0][product_id]"] == 803
    assert params["products[0][price]"] == "3999.99"
    assert params["products[0][quantity]"] == 1
    assert "products[0][sku]" not in params


@pytest.mark.parametrize("sentinel", [None, "", 0, "0"])
def test_write_schemas_accept_absent_variant_sentinels(sentinel):
    shipping = ShippingQuoteProduct.model_validate(
        {
            "product_id": 803,
            "variant_id": sentinel,
            "price": "3999.99",
            "quantity": 1,
        }
    )
    quantity = CartItemQuantityUpdateRequest.model_validate(
        {"product_id": 803, "variant_id": sentinel, "quantity": 1}
    )
    order = OrderProduct.model_validate(
        {
            "product_id": 803,
            "variant_id": sentinel,
            "price": "3999.99",
            "original_price": "4199.99",
            "quantity": 1,
        }
    )

    assert shipping.variant_id is None
    assert quantity.variant_id is None
    assert order.variant_id is None


def test_write_schemas_preserve_positive_variant_and_reject_invalid_value():
    assert ShippingQuoteProduct.model_validate(
        {
            "product_id": 803,
            "variant_id": "123",
            "price": "3999.99",
            "quantity": 1,
        }
    ).variant_id == 123
    assert CartItemQuantityUpdateRequest.model_validate(
        {"product_id": 803, "variant_id": "123", "quantity": 1}
    ).variant_id == 123
    assert OrderProduct.model_validate(
        {
            "product_id": 803,
            "variant_id": "123",
            "price": "3999.99",
            "original_price": "4199.99",
            "quantity": 1,
        }
    ).variant_id == 123

    with pytest.raises(ValidationError):
        ShippingQuoteProduct.model_validate(
            {
                "product_id": 803,
                "variant_id": "invalid",
                "price": "3999.99",
                "quantity": 1,
            }
        )
    with pytest.raises(ValidationError):
        CartItemQuantityUpdateRequest.model_validate(
            {"product_id": 803, "variant_id": "invalid", "quantity": 1}
        )
    with pytest.raises(ValidationError):
        OrderProduct.model_validate(
            {
                "product_id": 803,
                "variant_id": "invalid",
                "price": "3999.99",
                "original_price": "4199.99",
                "quantity": 1,
            }
        )


def test_order_shipping_quotation_is_optional_but_original_price_is_not():
    common_shipping = {
        "shipping_id": 1,
        "name": "PAC Tray",
        "value": "35.10",
    }
    assert OrderShipping.model_validate(common_shipping).quotation_id is None
    assert OrderShipping.model_validate(
        {**common_shipping, "quotation_id": None}
    ).quotation_id is None
    assert OrderShipping.model_validate(
        {**common_shipping, "quotation_id": 9}
    ).quotation_id == "9"

    with pytest.raises(ValidationError):
        OrderProduct.model_validate(
            {
                "product_id": 803,
                "variant_id": "0",
                "price": "3999.99",
                "quantity": 1,
            }
        )