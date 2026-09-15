from app.normalizers.product import normalize_product


def test_preserves_explicit_specs_and_their_source():
    product = normalize_product({"id": "1", "name": "Relógio", "mechanism": "Quartz",
        "Properties": [{"Property": {"name": "Movimento", "value": "Automático"}},
                       {"name": "Diâmetro da caixa", "value": "38 mm"}], "water_resistance_m": 100})
    assert product["mechanism"] == "Quartz"
    assert product["case_size"] == "38 mm"
    assert product["water_resistance_m"] == 100
    assert product["attribute_sources"]["mechanism"] == "field:mechanism"
    assert len(product["properties"]) == 2


def test_model_name_alone_does_not_create_product_specs():
    product = normalize_product({"id": "2", "name": "Seastar Diver Automático"})
    assert "water_resistance_m" not in product
    assert "mechanism" not in product
    assert product["attribute_sources"] == {}
