import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.resources.orders import DEFAULT_CUSTOMER_BIRTH_DATE, _tray_order_payload
from app.schemas.orders import OrderCreateRequest

BASE: dict[str, Any] = {
    "session_id": "2b0d972a0bbdcc223cae291bfc8d8d43",
    "shipping": {
        "shipping_id": "1",
        "quotation_id": "Q1",
        "name": "Sedex",
        "value": "74.97",
        "min_period": None,
        "max_period": 40,
    },
    "payment": {"method_id": "10545", "name": "Pix - Vindi"},
    "customer": {
        "type": "0",
        "name": "Joao",
        "cpf": "52998224725",
        "email": "joao@example.com",
        "phone": "43998640480",
    },
    "address": {
        "address": "Rua X",
        "zip_code": "86480000",
        "number": "225",
        "complement": "",
        "neighborhood": "Centro",
        "city": "Conselheiro Mairinck",
        "state": "PR",
        "country": "BRA",
        "type": "1",
    },
    "products": [
        {
            "product_id": "1307",
            "variant_id": None,
            "price": "3799.99",
            "original_price": "3799.99",
            "quantity": 1,
        }
    ],
}


def _key(container: Any, key: str) -> Any:
    return int(key) if isinstance(container, list) else key


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = copy.deepcopy(BASE)
    for path, value in overrides.items():
        keys = path.split(".")
        target = payload
        for key in keys[:-1]:
            target = target[_key(target, key)]
        target[_key(target, keys[-1])] = value
    return payload


ACCEPTED_CASES = {
    "baseline": {},
    "phone_with_country_code": {"customer.phone": "5543998640480"},
    "phone_with_plus_country_code": {"customer.phone": "+5543998640480"},
    "quotation_id_blank": {"shipping.quotation_id": ""},
    "quotation_id_none": {"shipping.quotation_id": None},
    "shipping_id_zero": {"shipping.shipping_id": 0},
    "shipping_id_blank": {"shipping.shipping_id": ""},
    "shipping_id_none": {"shipping.shipping_id": None},
    "method_id_none": {"payment.method_id": None},
    "variant_id_zero_string": {"products.0.variant_id": "0"},
    "complement_blank": {"address.complement": ""},
    "complement_none": {"address.complement": None},
    "min_period_none": {"shipping.min_period": None},
    "max_period_none": {"shipping.max_period": None},
    "birth_date_absent": {},
    "birth_date_present": {"customer.birth_date": "1990-05-17"},
}


@pytest.mark.parametrize("overrides", ACCEPTED_CASES.values(), ids=ACCEPTED_CASES.keys())
def test_accepted_nsagent_payloads(overrides):
    OrderCreateRequest.model_validate(_payload(**overrides))


REJECTED_CASES = {
    "session_id_too_long": {"session_id": "x" * 40},
    "shipping_extra_field": {"shipping.unexpected": "value"},
    "product_extra_field": {"products.0.unexpected": "value"},
    "original_price_missing": None,
    "price_with_comma": {"products.0.price": "3799,99"},
    "phone_nine_digits": {"customer.phone": "439986404"},
    "cpf_ten_digits": {"customer.cpf": "5299822472"},
    "state_three_letters": {"address.state": "PRR"},
    "country_not_brazil": {"address.country": "ARG"},
}


@pytest.mark.parametrize("overrides", REJECTED_CASES.values(), ids=REJECTED_CASES.keys())
def test_rejected_nsagent_payloads(overrides):
    if overrides is None:
        payload = _payload()
        del payload["products"][0]["original_price"]
    else:
        payload = _payload(**overrides)
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(payload)


def test_payload_without_birth_date_still_validates_and_defaults_upstream():
    validated = OrderCreateRequest.model_validate(_payload())
    tray_payload = _tray_order_payload(validated.model_dump(exclude_none=True))
    assert tray_payload["Order"]["Customer"]["birth_date"] == DEFAULT_CUSTOMER_BIRTH_DATE


def test_payload_with_birth_date_is_preserved_upstream():
    validated = OrderCreateRequest.model_validate(
        _payload(**{"customer.birth_date": "1990-05-17"})
    )
    tray_payload = _tray_order_payload(validated.model_dump(exclude_none=True))
    assert tray_payload["Order"]["Customer"]["birth_date"] == "1990-05-17"


def test_validation_handler_reports_loc_without_leaking_field_value(monkeypatch):
    for key, value in {
        "TRAY_API_BASE": "https://tray.test/web_api",
        "TRAY_CODE": "code",
        "TRAY_CONSUMER_KEY": "key",
        "TRAY_CONSUMER_SECRET": "secret",
        "TRAY_STORE_CODE": "687890",
        "TRAY_ADAPTER_TOKEN": "adapter-token",
    }.items():
        monkeypatch.setenv(key, value)

    api = TestClient(main.app)
    payload = _payload(**{"customer.phone": "439986404"})
    result = api.post(
        "/internal/orders",
        json=payload,
        headers={"Authorization": "Bearer adapter-token"},
    )
    assert result.status_code == 422
    body = result.json()
    assert isinstance(body["detail"], list)
    assert any("phone" in ".".join(str(part) for part in error["loc"]) for error in body["detail"])
    assert "439986404" not in result.text
