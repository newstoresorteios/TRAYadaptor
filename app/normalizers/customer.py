def normalize_address(v):
    return {key: v.get(key) for key in ("id", "customer_id", "recipient", "address", "number", "complement", "neighborhood", "city", "state", "zip_code", "country", "type", "active", "description", "type_delivery", "not_list")}


def normalize_customer(v):
    return {key: v.get(key) for key in ("id", "name", "rg", "cpf", "phone", "cellphone", "birth_date", "gender", "email", "nickname", "total_orders", "observation", "type", "cnpj", "company_name", "state_inscription", "reseller", "discount", "credit_limit", "indicator_id", "profile_customer_id", "last_purchase", "last_visit", "address", "zip_code", "number", "complement", "neighborhood", "city", "state", "newsletter", "created", "registration_date", "modified", "addresses") if key in v}
