from typing import Any, Iterator

from slims.slims import Criterion, Record, Slims


class PaginatedSlims(Slims):
    def __init__(
        self,
        name: str,
        url: str,
        username: str | None = None,
        password: str | None = None,
        oauth: bool = False,
        client_id: str | None = None,
        client_secret: str | None = None,
        repo_location: str | None = None,
        local_host: str = "localhost",
        local_port: int = 5000,
        page_size: int = 100,
        **request_params: Any
    ) -> None:
        self.page_size = page_size
        super().__init__(
            name=name,
            url=url,
            username=username,
            password=password,
            oauth=oauth,
            client_id=client_id,
            client_secret=client_secret,
            repo_location=repo_location,
            local_host=local_host,
            local_port=local_port,
            **request_params
        )

    def fetch(
        self,
        table: str,
        criteria: Criterion,
        sort: list[str] | None = None,
        start: int | None = None,
        end: int | None = None,
    ) -> list[Record]:
        return [
            record
            for page in self.iter_fetch(
                table=table,
                criteria=criteria,
                sort=sort,
                start=start,
                end=end,
            )
            for record in page
        ]

    def iter_fetch(
        self,
        table: str,
        criteria: Criterion,
        sort: list[str] | None = None,
        start: int | None = None,
        end: int | None = None,
    ) -> Iterator[list[Record]]:
        _start = start or 0
        _end = end or float("inf")

        while _page := super().fetch(
            table=table,
            criteria=criteria,
            sort=sort,
            start=_start,
            end=min(_end, _start + self.page_size),
        ):
            yield _page
            _start += self.page_size
