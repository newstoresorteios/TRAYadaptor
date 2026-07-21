from .common import Resource
from ..normalizers.brand import normalize_brand


class BrandResource(Resource):
    path, plural, singular, normalizer = "/products/brands", "Brands", "brand", staticmethod(normalize_brand)
