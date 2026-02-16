from __future__ import annotations

from abc import ABC, abstractmethod


class BaseChannel(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send_reply(self, chat_id: str, text: str) -> None: ...
