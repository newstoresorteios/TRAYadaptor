from ..normalizers.common import normalized_list
from ..normalizers.user import normalize_user


class UserResource:
    def __init__(self, client): self.client = client
    async def list(self, params=None):
        return normalized_list(await self.client.request("GET", "/users", params=params), "Users", "user", normalize_user, "users")
