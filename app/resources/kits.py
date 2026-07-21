from .common import Resource
from ..normalizers.kit import normalize_kit


class KitResource(Resource):
    path, plural, singular, normalizer = "/products/kits", "Kits", "kit", staticmethod(normalize_kit)
